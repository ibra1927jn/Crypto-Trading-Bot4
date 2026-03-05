"""
CT4 LAB — ESTRATEGIAS AVANZADAS (Capital Real: $100)
=====================================================
Compara Bollinger Bounce vs variantes avanzadas.
TODO con $100 para reflejar la realidad.

Estrategias:
  A. Bollinger Bounce (producción actual)
  B. BB + Multi-Timeframe (filtro EMA50 1h simulado)
  C. BB + RSI Divergence (solo compra si hay divergencia bullish)
  D. Supertrend (canal ATR dinámico)
  E. Donchian Breakout (compra en nuevos máximos de 20 velas)
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

CAPITAL = 100  # ← $100 REALES
FEE = 0.001    # 0.1% Binance

def calc(df):
    c, h, lo = df['close'], df['high'], df['low']
    df['EMA9'] = c.ewm(span=9).mean()
    df['EMA21'] = c.ewm(span=21).mean()
    df['EMA50'] = c.ewm(span=50).mean()
    df['EMA200'] = c.ewm(span=200).mean()
    d = c.diff()
    g = d.where(d > 0, 0).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    rs = g / l.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    tr = pd.concat([h - lo, abs(h - c.shift(1)), abs(lo - c.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    pdm = h.diff().where(lambda x: (x > 0) & (x > -lo.diff()), 0)
    mdm = (-lo.diff()).where(lambda x: (x > 0) & (x > h.diff()), 0)
    pdi = 100 * (pdm.rolling(14).mean() / df['ATR'])
    mdi = 100 * (mdm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['VSMA'] = df['volume'].rolling(20).mean()
    bb_mid = c.rolling(20).mean()
    bs = c.rolling(20).std()
    df['BB_MID'] = bb_mid
    df['BB_LO'] = bb_mid - 2 * bs
    df['BB_HI'] = bb_mid + 2 * bs
    df['BB_PCT'] = (c - df['BB_LO']) / (df['BB_HI'] - df['BB_LO'] + 1e-10)
    df['DC_HI'] = h.rolling(20).max()
    df['DC_LO'] = lo.rolling(20).min()
    # Supertrend
    atr = df['ATR']
    hl2 = (h + lo) / 2
    df['ST_UP'] = hl2 - 2.0 * atr
    df['ST_DN'] = hl2 + 2.0 * atr
    st = pd.Series(index=df.index, dtype=float)
    st_dir = pd.Series(index=df.index, dtype=float)
    for i in range(1, len(df)):
        if pd.isna(df['ST_UP'].iloc[i]):
            st.iloc[i] = c.iloc[i]; st_dir.iloc[i] = 1; continue
        prev_st = st.iloc[i-1] if not pd.isna(st.iloc[i-1]) else c.iloc[i]
        prev_dir = st_dir.iloc[i-1] if not pd.isna(st_dir.iloc[i-1]) else 1
        up = max(df['ST_UP'].iloc[i], prev_st) if prev_dir == 1 else df['ST_UP'].iloc[i]
        dn = min(df['ST_DN'].iloc[i], prev_st) if prev_dir == -1 else df['ST_DN'].iloc[i]
        if prev_dir == 1:
            if c.iloc[i] < up: st_dir.iloc[i] = -1; st.iloc[i] = dn
            else: st_dir.iloc[i] = 1; st.iloc[i] = up
        else:
            if c.iloc[i] > dn: st_dir.iloc[i] = 1; st.iloc[i] = up
            else: st_dir.iloc[i] = -1; st.iloc[i] = dn
    df['ST'] = st
    df['ST_DIR'] = st_dir
    # Multi-timeframe: EMA50 on 1h (simulate by using EMA on 12× period)
    df['EMA50_1H'] = c.ewm(span=50*12).mean()
    # RSI divergence detection
    df['RSI_MIN_5'] = df['RSI'].rolling(5).min()
    df['PRICE_MIN_5'] = lo.rolling(5).min()
    df['RSI_MIN_10'] = df['RSI'].rolling(10).min()
    df['PRICE_MIN_10'] = lo.rolling(10).min()
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

def backtest(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0,
             trailing=True, capital=CAPITAL):
    cap = capital; peak = capital; dd = 0; pos = None; trades = []
    min_notional = 12  # Binance min order $12
    for i in range(250, len(df) - 1):
        r, p1, p2 = df.iloc[i], df.iloc[i - 1], df.iloc[i - 2]
        p3 = df.iloc[i - 3] if i >= 3 else p2
        if pos is None:
            if buy_fn(r, p1, p2, p3):
                atr = v(r, 'ATR', 100)
                alloc = cap * 0.30  # 30% max
                if alloc < min_notional:
                    continue  # No enough capital for trade
                sz = alloc / r['close']
                cost = alloc * FEE  # Entry fee
                pos = {'e': r['close'], 'sl': r['close'] - sl_m * atr,
                       'tp': r['close'] + tp_m * atr, 'sz': sz, 'b': i,
                       'pk': r['close'], 'fee': cost}
        else:
            p = r['close']; pos['pk'] = max(pos['pk'], p)
            if trailing and p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', 100))
            pnl = None; t = None
            if p <= pos['sl']: pnl = (pos['sl'] - pos['e']) * pos['sz']; t = 'SL'
            elif p >= pos['tp']: pnl = (pos['tp'] - pos['e']) * pos['sz']; t = 'TP'
            elif exit_fn(r, p1): pnl = (p - pos['e']) * pos['sz']; t = 'EXIT'
            if pnl is not None:
                exit_fee = p * pos['sz'] * FEE
                pnl -= (pos['fee'] + exit_fee)  # Subtract fees
                cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 't': t, 'bars': i - pos['b'],
                               'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
                pos = None
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']
        exit_fee = df.iloc[-1]['close'] * pos['sz'] * FEE
        pnl -= (pos['fee'] + exit_fee)
        cap += pnl; trades.append({'pnl': pnl, 't': 'OPEN', 'bars': 0,
                                    'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    max_cl = 0; cur = 0
    for t in trades:
        if t['pnl'] <= 0: cur += 1; max_cl = max(max_cl, cur)
        else: cur = 0
    avg_pct = np.mean([t['pct'] for t in trades]) if trades else 0
    return {
        'name': name, 'n': len(trades), 'w': len(w), 'l': len(lo),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'max_cl': max_cl, 'avg_pct': avg_pct,
        'total_fees': sum(t.get('pnl', 0) for t in trades) - sum(t['pnl'] for t in trades) if False else 0,
    }

# ═══════════════════════════════════════════
# EXITS
# ═══════════════════════════════════════════
def exit_bb(r, p):
    if v(r, 'BB_PCT') > 0.95: return True
    if v(p, 'EMA9') >= v(p, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'): return True
    if r['close'] < v(r, 'EMA200') * 0.985: return True
    return False

def exit_ema(r, p):
    if v(p, 'EMA9') >= v(p, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'): return True
    if r['close'] < v(r, 'EMA200') * 0.985: return True
    return False

def exit_supertrend(r, p):
    if v(r, 'ST_DIR') == -1 and v(p, 'ST_DIR') == 1: return True
    return False

# ═══════════════════════════════════════════
# STRATEGIES
# ═══════════════════════════════════════════

# A. Bollinger Bounce (producción actual)
def buy_bb(r, p1, p2, p3):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX'); macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro

# B. BB + Multi-Timeframe (filtro tendencia 1h)
def buy_bb_mtf(r, p1, p2, p3):
    if not buy_bb(r, p1, p2, p3): return False
    # Filtro extra: precio debe estar sobre EMA50 de 1h
    ema50_1h = v(r, 'EMA50_1H')
    return r['close'] > ema50_1h * 0.995

# C. BB + RSI Divergence
def buy_bb_div(r, p1, p2, p3):
    if not buy_bb(r, p1, p2, p3): return False
    # Divergencia bullish: precio hace nuevo mínimo pero RSI no
    price_lower = r['low'] <= v(r, 'PRICE_MIN_10') * 1.002
    rsi_higher = v(r, 'RSI') > v(r, 'RSI_MIN_10') * 1.05
    return price_lower and rsi_higher

# D. Supertrend (puro)
def buy_supertrend(r, p1, p2, p3):
    # Compra cuando Supertrend cambia de bajista a alcista
    curr_dir = v(r, 'ST_DIR', 0)
    prev_dir = v(p1, 'ST_DIR', 0)
    macro = r['close'] > v(r, 'EMA200') * 0.99
    return prev_dir == -1 and curr_dir == 1 and macro

# E. Donchian Breakout
def buy_donchian(r, p1, p2, p3):
    # Compra cuando el precio rompe el canal superior de Donchian
    dc_hi = v(p1, 'DC_HI')  # Max de 20 velas anteriores
    adx = v(r, 'ADX')
    macro = r['close'] > v(r, 'EMA200') * 0.99
    vol = r['volume'] > v(r, 'VSMA') * 0.8
    return r['close'] > dc_hi and adx > 20 and macro and vol

# F. BB Tight (versión más selectiva: BB% < 0.10 + RSI < 30)
def buy_bb_tight(r, p1, p2, p3):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX'); macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.10 and prsi < 30 and rsi > prsi and adx > 15 and macro

# G. Combo: Supertrend + BB (compra en Supertrend si BB confirma suelo)
def buy_st_bb(r, p1, p2, p3):
    st_buy = v(r, 'ST_DIR') == 1  # Supertrend alcista
    bb_low = v(r, 'BB_PCT', 0.5) < 0.30  # Precio en zona baja de BB
    rsi_ok = v(r, 'RSI', 50) < 45 and v(r, 'RSI', 50) > v(p1, 'RSI', 50)
    macro = r['close'] > v(r, 'EMA200') * 0.99
    adx = v(r, 'ADX') > 15
    return st_buy and bb_low and rsi_ok and macro and adx


async def main():
    print("=" * 80)
    print(f"🔬 CT4 LAB — ESTRATEGIAS AVANZADAS (Capital: ${CAPITAL})")
    print("=" * 80)
    print(f"  ⚠️ Con ${CAPITAL}, las COMISIONES (0.1%) importan mucho")
    print(f"     Trade de $30 (30% de ${CAPITAL}): fee = $0.06 ida + $0.06 vuelta = $0.12")
    print(f"     Para ganar, cada trade necesita > 0.4% de movimiento")

    exchange = ccxt.binance({'sandbox': True})
    all_candles = []
    since = int(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(2026, 3, 5, 6, 0, tzinfo=timezone.utc).timestamp() * 1000)
    while since < end_ts:
        try:
            candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=1000)
            if not candles: break
            all_candles.extend(candles)
            since = candles[-1][0] + 1
            await asyncio.sleep(0.3)
        except: break
    await exchange.close()

    seen = set(); unique = []
    for c in all_candles:
        if c[0] not in seen: seen.add(c[0]); unique.append(c)
    unique.sort(key=lambda x: x[0])
    df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)

    total_days = len(df) * 5 / 60 / 24
    bh = (df.iloc[-1]['close'] - df.iloc[250]['close']) / df.iloc[250]['close'] * 100
    print(f"\n  📊 Data: {len(df)} velas ({total_days:.0f} días)")
    print(f"  B&H: {bh:+.1f}%")
    print(f"  Precio: ${df['close'].min():.0f} — ${df['close'].max():.0f}")

    # ═══ 70/30 Split ═══
    cut = int(len(df) * 0.70)
    df_in = df.iloc[:cut].copy()
    df_out = df.iloc[max(0, cut-250):].copy()
    df_out = calc(df_out)

    configs = [
        ("A. BB PRODUCCIÓN",    buy_bb,         exit_bb,        1.5, 3.0),
        ("B. BB + MTF (1h)",    buy_bb_mtf,     exit_bb,        1.5, 3.0),
        ("C. BB + RSI Diverg",  buy_bb_div,     exit_bb,        1.5, 3.0),
        ("D. SUPERTREND",       buy_supertrend, exit_supertrend,2.0, 4.0),
        ("E. DONCHIAN BREAK",   buy_donchian,   exit_ema,       2.0, 4.0),
        ("F. BB TIGHT (10/30)", buy_bb_tight,   exit_bb,        1.5, 3.0),
        ("G. SUPERTREND + BB",  buy_st_bb,      exit_bb,        1.5, 3.0),
    ]

    # ═══ IN-SAMPLE ═══
    print(f"\n{'=' * 80}")
    print(f"📊 IN-SAMPLE ({df_in.index[0].strftime('%m/%d')} → {df_in.index[-1].strftime('%m/%d')}) | Capital: ${CAPITAL}")
    print(f"{'=' * 80}")
    hdr = f"   {'Estrategia':<22} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>9} {'DD%':>5} {'PF':>5} {'CL':>3} {'%avg':>6}"
    print(hdr)
    print("   " + "-" * 65)
    in_results = []
    for name, buy, exit_fn, sl, tp in configs:
        r = backtest(df_in, name, buy, exit_fn, sl, tp)
        in_results.append(r)
        e = "🟢" if r['pnl'] > 0 else "🔴"
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<20} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+7.2f} {r['dd']:>4.1f}% {pf:>5} {r['max_cl']:>3} {r['avg_pct']:>+5.1f}%")

    # ═══ OUT-OF-SAMPLE (CIEGO) ═══
    print(f"\n{'=' * 80}")
    print(f"🔮 OUT-OF-SAMPLE CIEGO ({df.index[cut].strftime('%m/%d')} → {df.index[-1].strftime('%m/%d')}) | Capital: ${CAPITAL}")
    print(f"{'=' * 80}")
    print(hdr)
    print("   " + "-" * 65)
    out_results = []
    for name, buy, exit_fn, sl, tp in configs:
        r = backtest(df_out, name, buy, exit_fn, sl, tp)
        out_results.append(r)
        e = "🟢" if r['pnl'] > 0 else "🔴"
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<20} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+7.2f} {r['dd']:>4.1f}% {pf:>5} {r['max_cl']:>3} {r['avg_pct']:>+5.1f}%")

    # ═══ WALK-FORWARD ═══
    print(f"\n{'=' * 80}")
    print(f"⚖️  WALK-FORWARD (Capital: ${CAPITAL})")
    print(f"{'=' * 80}")
    print(f"   {'Estrategia':<22} {'In $':>8} {'Out $':>8} {'Verdict':>12}")
    print("   " + "-" * 55)
    for i_r, o_r in zip(in_results, out_results):
        if o_r['pnl'] > 0 and i_r['pnl'] > 0: v2 = "✅ REAL"
        elif o_r['pnl'] > 0 and i_r['pnl'] <= 0: v2 = "🔄 MEJORA"
        elif o_r['pnl'] <= 0 and i_r['pnl'] > 0: v2 = "❌ OVERFIT"
        elif o_r['n'] == 0: v2 = "🤫 SIN TRADES"
        else: v2 = "💀 MUERTA"
        print(f"   {i_r['name']:<22} ${i_r['pnl']:>+6.2f} ${o_r['pnl']:>+6.2f}   {v2}")

    # ═══ RANKING ═══
    ranked = sorted(out_results, key=lambda x: x['pnl'], reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i+4}." for i in range(4)]
    print(f"\n{'=' * 80}")
    print(f"🏆 RANKING CIEGO — Los ${CAPITAL} de la VERDAD")
    print(f"{'=' * 80}")
    for i, r in enumerate(ranked):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        bar = "█" * max(1, int(max(0, r['pnl']) * 5))
        neg = "▓" * max(0, int(abs(min(0, r['pnl'])) * 5))
        ret = (r['pnl'] / CAPITAL) * 100
        print(f"  {medals[i]} {e} {r['name']:<22} ${r['pnl']:>+6.2f} ({ret:>+5.1f}%) | "
              f"WR {r['wr']:>3.0f}% | PF {r['pf']:>4.1f} | DD {r['dd']:>3.1f}%  {bar}{neg}")
    
    best = ranked[0]
    print(f"\n  🏆 LA MEJOR PARA ${CAPITAL}: {best['name']}")
    print(f"     ${best['pnl']:>+.2f} ({best['pnl']/CAPITAL*100:>+.1f}%) | {best['n']} trades | WR {best['wr']:.0f}% | DD {best['dd']:.1f}%")
    print(f"     Capital final: ${best['cap']:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
