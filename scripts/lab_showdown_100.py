"""
CT4 LAB — SHOWDOWN FINAL: TODAS las estrategias con $100
==========================================================
14 estrategias. $100 capital. Comisiones reales (0.1%).
Walk-forward: 70% in-sample / 30% out-of-sample CIEGO.
La prueba definitiva.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

CAPITAL = 100
FEE = 0.001

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
    df['BB_WIDTH'] = (df['BB_HI'] - df['BB_LO']) / bb_mid * 100
    df['DC_HI'] = h.rolling(20).max()
    df['DC_LO'] = lo.rolling(20).min()
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_S'] = df['MACD'].ewm(span=9).mean()
    df['MACD_H'] = df['MACD'] - df['MACD_S']
    rsi = df['RSI']
    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    df['SRSI'] = (rsi - rsi_min) / (rsi_max - rsi_min + 1e-10) * 100
    df['SRSI_K'] = df['SRSI'].rolling(3).mean()
    df['SRSI_D'] = df['SRSI_K'].rolling(3).mean()
    # Supertrend
    hl2 = (h + lo) / 2
    df['ST_UP'] = hl2 - 2.0 * df['ATR']
    df['ST_DN'] = hl2 + 2.0 * df['ATR']
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
    df['ST'] = st; df['ST_DIR'] = st_dir
    # Multi-timeframe
    df['EMA50_1H'] = c.ewm(span=50*12).mean()
    # RSI divergence
    df['RSI_MIN_10'] = df['RSI'].rolling(10).min()
    df['PRICE_MIN_10'] = lo.rolling(10).min()
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

def backtest(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0,
             trailing=True, adapt_sl=False):
    cap = CAPITAL; peak = CAPITAL; dd = 0; pos = None; trades = []
    min_notional = 12
    for i in range(250, len(df) - 1):
        r, p1, p2 = df.iloc[i], df.iloc[i - 1], df.iloc[i - 2]
        p3 = df.iloc[i - 3] if i >= 3 else p2
        if pos is None:
            if buy_fn(r, p1, p2, p3):
                atr = v(r, 'ATR', 100); adx = v(r, 'ADX', 30)
                alloc = cap * 0.30
                if alloc < min_notional: continue
                if adapt_sl:
                    sm = 2.5 if adx > 50 else 2.0 if adx > 35 else 1.5
                    tm = 4.0 if adx > 50 else 3.5 if adx > 35 else 3.0
                else:
                    sm = sl_m; tm = tp_m
                sz = alloc / r['close']
                entry_fee = alloc * FEE
                pos = {'e': r['close'], 'sl': r['close'] - sm * atr,
                       'tp': r['close'] + tm * atr, 'sz': sz, 'b': i,
                       'pk': r['close'], 'fee': entry_fee}
        else:
            p = r['close']; pos['pk'] = max(pos['pk'], p)
            if trailing and p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', 100))
            pnl = None
            if p <= pos['sl']: pnl = (pos['sl'] - pos['e']) * pos['sz']
            elif p >= pos['tp']: pnl = (pos['tp'] - pos['e']) * pos['sz']
            elif exit_fn(r, p1): pnl = (p - pos['e']) * pos['sz']
            if pnl is not None:
                exit_fee = p * pos['sz'] * FEE
                pnl -= (pos['fee'] + exit_fee)
                cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
                pos = None
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']
        exit_fee = df.iloc[-1]['close'] * pos['sz'] * FEE
        pnl -= (pos['fee'] + exit_fee)
        cap += pnl; trades.append({'pnl': pnl, 'pct': 0})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    mcl = 0; cur = 0
    for t in trades:
        if t['pnl'] <= 0: cur += 1; mcl = max(mcl, cur)
        else: cur = 0
    return {
        'name': name, 'n': len(trades), 'w': len(w), 'l': len(lo),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'mcl': mcl, 'avg': np.mean([t['pct'] for t in trades]) if trades else 0,
    }

# ═══════════════════════════════════════════
# EXITS
# ═══════════════════════════════════════════
def exit_ema(r, p):
    return ((v(p, 'EMA9') >= v(p, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'))
            or r['close'] < v(r, 'EMA200') * 0.985)
def exit_bb(r, p):
    return v(r, 'BB_PCT') > 0.95 or exit_ema(r, p)
def exit_never(r, p):
    return False
def exit_st(r, p):
    return v(r, 'ST_DIR') == -1 and v(p, 'ST_DIR') == 1

# ═══════════════════════════════════════════
# 14 STRATEGIES
# ═══════════════════════════════════════════

# --- ORIGINALES ---
def buy_original(r, p1, p2, p3):
    return (r['close'] > v(r, 'EMA200') and v(r, 'ADX') > 20 and
            r['volume'] > v(r, 'VSMA') and v(p1, 'RSI') < 35 and v(r, 'RSI') > v(p1, 'RSI'))

def buy_momentum(r, p1, p2, p3):
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX'); atr = v(r, 'ATR', 100)
    atr_pct = (atr / r['close']) * 100; hv = atr_pct > 0.5
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']: return True
    rt = 40 if hv else 35; at = 15 if hv else 20; mt = 0.02 if hv else 0.01
    return (r['close'] > v(r, 'EMA200') * (1 - mt) and adx > at and
            r['volume'] > v(r, 'VSMA') * 0.8 and prsi < rt and rsi > prsi and prsi > p2rsi)

def buy_v21(r, p1, p2, p3):
    return buy_momentum(r, p1, p2, p3)

# --- BOLLINGER FAMILY ---
def buy_bb(r, p1, p2, p3):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX'); macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro

def buy_bb_tight(r, p1, p2, p3):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX'); macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.10 and prsi < 30 and rsi > prsi and adx > 15 and macro

def buy_bb_mtf(r, p1, p2, p3):
    if not buy_bb(r, p1, p2, p3): return False
    return r['close'] > v(r, 'EMA50_1H') * 0.995

def buy_bb_div(r, p1, p2, p3):
    if not buy_bb(r, p1, p2, p3): return False
    price_lower = r['low'] <= v(r, 'PRICE_MIN_10') * 1.002
    rsi_higher = v(r, 'RSI') > v(r, 'RSI_MIN_10') * 1.05
    return price_lower and rsi_higher

def buy_squeeze(r, p1, p2, p3):
    width = v(r, 'BB_WIDTH', 5); pwidth = v(p1, 'BB_WIDTH', 5)
    squeeze = pwidth < 2.0; breakout = r['close'] > v(r, 'BB_HI') * 0.998
    trend = r['close'] > v(r, 'EMA200')
    adx_rising = v(r, 'ADX') > v(p1, 'ADX') and v(r, 'ADX') > 20
    return squeeze and breakout and trend and adx_rising

# --- OTROS ---
def buy_macd(r, p1, p2, p3):
    cross = v(p1, 'MACD') < v(p1, 'MACD_S') and v(r, 'MACD') >= v(r, 'MACD_S')
    macro = r['close'] > v(r, 'EMA200') * 0.99; adx = v(r, 'ADX') > 15
    rsi = v(r, 'RSI', 50) < 55
    return cross and macro and adx and rsi

def buy_stoch_rsi(r, p1, p2, p3):
    sk = v(r, 'SRSI_K', 50); sd = v(r, 'SRSI_D', 50); psk = v(p1, 'SRSI_K', 50)
    cross_up = psk < sd and sk >= sd; oversold = psk < 25
    trend = r['close'] > v(r, 'EMA200') * 0.99; adx = v(r, 'ADX') > 15
    return cross_up and oversold and trend and adx

def buy_ultimate(r, p1, p2, p3):
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX'); atr = v(r, 'ATR', 100)
    atr_pct = (atr / r['close']) * 100; hv = atr_pct > 0.5
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']: return True
    rsi_t = 43 if hv else 38; adx_t = 15 if hv else 20; mt = 0.02 if hv else 0.01
    marea = r['close'] > v(r, 'EMA200') * (1 - mt)
    fuerza = adx > adx_t; ballenas = r['volume'] > v(r, 'VSMA') * 0.8
    pb = prsi < rsi_t and rsi > prsi; mom = rsi > prsi and prsi > p2rsi
    bb = v(r, 'BB_PCT', 0.5) < 0.35
    return marea and fuerza and ballenas and pb and mom and bb

def buy_supertrend(r, p1, p2, p3):
    curr = v(r, 'ST_DIR', 0); prev = v(p1, 'ST_DIR', 0)
    macro = r['close'] > v(r, 'EMA200') * 0.99
    return prev == -1 and curr == 1 and macro

def buy_donchian(r, p1, p2, p3):
    dc_hi = v(p1, 'DC_HI'); adx = v(r, 'ADX')
    macro = r['close'] > v(r, 'EMA200') * 0.99; vol = r['volume'] > v(r, 'VSMA') * 0.8
    return r['close'] > dc_hi and adx > 20 and macro and vol

def buy_st_bb(r, p1, p2, p3):
    st_buy = v(r, 'ST_DIR') == 1
    bb_low = v(r, 'BB_PCT', 0.5) < 0.30
    rsi_ok = v(r, 'RSI', 50) < 45 and v(r, 'RSI', 50) > v(p1, 'RSI', 50)
    macro = r['close'] > v(r, 'EMA200') * 0.99; adx = v(r, 'ADX') > 15
    return st_buy and bb_low and rsi_ok and macro and adx


async def main():
    print("=" * 90)
    print(f"🏆 CT4 LAB — SHOWDOWN FINAL: 14 Estrategias × ${CAPITAL} × Comisiones Reales")
    print("=" * 90)

    exchange = ccxt.binance({'sandbox': True})
    all_candles = []
    since = int(datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime(2026, 3, 5, 7, 0, tzinfo=timezone.utc).timestamp() * 1000)
    while since < end_ts:
        try:
            candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=1000)
            if not candles: break
            all_candles.extend(candles); since = candles[-1][0] + 1
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
    print(f"  📊 Calculando indicadores para {len(df)} velas...")
    df = calc(df)
    total_days = len(df) * 5 / 60 / 24

    print(f"  📊 Data: {len(df)} velas ({total_days:.0f} días)")
    print(f"  Rango: {df.index[0].strftime('%m/%d')} → {df.index[-1].strftime('%m/%d')}")
    print(f"  Precio: ${df['close'].min():.0f} — ${df['close'].max():.0f}")

    # Split
    cut = int(len(df) * 0.70)
    df_in = df.iloc[:cut].copy()
    oos_start = max(0, cut - 250)
    df_out = df.iloc[oos_start:].copy()
    df_out = calc(df_out)
    print(f"  In-Sample:  {df_in.index[0].strftime('%m/%d')} → {df_in.index[-1].strftime('%m/%d')} ({len(df_in)} velas)")
    print(f"  Out-Sample: {df.index[cut].strftime('%m/%d')} → {df.index[-1].strftime('%m/%d')} ({len(df)-cut} velas)")

    configs = [
        # (name, buy, exit, sl, tp, trailing, adapt_sl)
        ("01. Original V1",      buy_original,   exit_ema,  1.5, 3.0, False, False),
        ("02. Momentum V2",      buy_momentum,   exit_ema,  1.5, 3.0, False, False),
        ("03. V2.1 Prod+Trail",  buy_v21,        exit_ema,  1.5, 3.0, True,  False),
        ("04. BB Bounce ★",      buy_bb,         exit_bb,   1.5, 3.0, True,  False),
        ("05. BB Tight",         buy_bb_tight,   exit_bb,   1.5, 3.0, True,  False),
        ("06. BB + MTF (1h)",    buy_bb_mtf,     exit_bb,   1.5, 3.0, True,  False),
        ("07. BB + RSI Diverg",  buy_bb_div,     exit_bb,   1.5, 3.0, True,  False),
        ("08. BB Squeeze",       buy_squeeze,    exit_never,1.5, 3.0, False, False),
        ("09. MACD Momentum",    buy_macd,       exit_ema,  1.5, 3.0, True,  False),
        ("10. Stochastic RSI",   buy_stoch_rsi,  exit_ema,  1.5, 3.0, True,  False),
        ("11. Ultimate V2",      buy_ultimate,   exit_ema,  1.5, 3.0, True,  True),
        ("12. Supertrend",       buy_supertrend, exit_st,   2.0, 4.0, True,  False),
        ("13. Donchian Break",   buy_donchian,   exit_ema,  2.0, 4.0, True,  False),
        ("14. Supertrend+BB",    buy_st_bb,      exit_bb,   1.5, 3.0, True,  False),
    ]

    # IN-SAMPLE
    print(f"\n{'=' * 90}")
    print(f"📊 IN-SAMPLE | Capital: ${CAPITAL}")
    print(f"{'=' * 90}")
    hdr = f"   {'#':>2} {'Estrategia':<22} {'T':>3} {'W':>2} {'L':>2} {'WR':>4} {'PnL':>9} {'DD%':>5} {'PF':>5} {'CL':>3}"
    print(hdr); print("   " + "-" * 68)
    in_r = []
    for name, buy, ex, sl, tp, tr, ad in configs:
        r = backtest(df_in, name, buy, ex, sl, tp, trailing=tr, adapt_sl=ad)
        in_r.append(r)
        e = "🟢" if r['pnl'] > 0 else "🔴"
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<22} {r['n']:>3} {r['w']:>2} {r['l']:>2} {r['wr']:>3.0f}% ${r['pnl']:>+7.2f} {r['dd']:>4.1f}% {pf:>5} {r['mcl']:>3}")

    # OUT-OF-SAMPLE
    print(f"\n{'=' * 90}")
    print(f"🔮 OUT-OF-SAMPLE CIEGO | Capital: ${CAPITAL}")
    print(f"{'=' * 90}")
    print(hdr); print("   " + "-" * 68)
    out_r = []
    for name, buy, ex, sl, tp, tr, ad in configs:
        r = backtest(df_out, name, buy, ex, sl, tp, trailing=tr, adapt_sl=ad)
        out_r.append(r)
        e = "🟢" if r['pnl'] > 0 else "🔴"
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<22} {r['n']:>3} {r['w']:>2} {r['l']:>2} {r['wr']:>3.0f}% ${r['pnl']:>+7.2f} {r['dd']:>4.1f}% {pf:>5} {r['mcl']:>3}")

    # WALK-FORWARD
    print(f"\n{'=' * 90}")
    print(f"⚖️  WALK-FORWARD — ¿Quién sobrevive con ${CAPITAL}?")
    print(f"{'=' * 90}")
    print(f"   {'Estrategia':<22} {'In':>8} {'Out':>8} {'Verdict':>14}")
    print("   " + "-" * 55)
    for ir, orr in zip(in_r, out_r):
        if orr['pnl'] > 0 and ir['pnl'] > 0: vd = "✅ REAL"
        elif orr['pnl'] > 0 and ir['pnl'] <= 0: vd = "🔄 MEJORA"
        elif orr['pnl'] <= 0 and ir['pnl'] > 0: vd = "❌ OVERFIT"
        elif orr['n'] == 0: vd = "🤫 SIN TRADES"
        else: vd = "💀 MUERTA"
        print(f"   {ir['name']:<22} ${ir['pnl']:>+6.2f} ${orr['pnl']:>+6.2f}   {vd}")

    # RANKING
    ranked = sorted(out_r, key=lambda x: x['pnl'], reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i+4:>2}." for i in range(11)]
    print(f"\n{'=' * 90}")
    print(f"🏆 RANKING FINAL — ${CAPITAL} REALES, COMISIONES REALES, TEST CIEGO")
    print(f"{'=' * 90}")
    for i, r in enumerate(ranked):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        ret = r['pnl'] / CAPITAL * 100
        bar = "█" * max(0, int(max(0, r['pnl']) * 4)) if r['pnl'] > 0 else "▓" * min(20, max(1, int(abs(r['pnl']) * 4)))
        sign = "" if r['pnl'] > 0 else "-"
        print(f"  {medals[i]} {e} {r['name']:<22} ${r['pnl']:>+6.2f} ({ret:>+5.1f}%) | "
              f"WR {r['wr']:>3.0f}% | PF {r['pf']:>4.1f} | DD {r['dd']:>3.1f}% | CL {r['mcl']:>2}  {bar}")

    # TOP 3 summary
    print(f"\n{'=' * 90}")
    print(f"💎 VEREDICTO — Los 3 mejores con ${CAPITAL}")
    print(f"{'=' * 90}")
    for i, r in enumerate(ranked[:3]):
        ret = r['pnl'] / CAPITAL * 100
        # Check walk-forward
        ir_match = [x for x in in_r if x['name'] == r['name']][0]
        wf = "✅" if ir_match['pnl'] > 0 and r['pnl'] > 0 else "🔄" if r['pnl'] > 0 else "❌"
        print(f"\n  {medals[i]} {r['name']}")
        print(f"     PnL: ${r['pnl']:>+.2f} ({ret:>+.1f}%) | Capital final: ${r['cap']:.2f}")
        print(f"     {r['n']} trades | WR {r['wr']:.0f}% | PF {r['pf']:.1f} | DD {r['dd']:.1f}% | Max pérdidas seguidas: {r['mcl']}")
        print(f"     Walk-Forward: {wf} In=${ir_match['pnl']:+.2f} → Out=${r['pnl']:+.2f}")

if __name__ == "__main__":
    asyncio.run(main())
