"""
CT4 LAB — LA MÁQUINA DEL TIEMPO DE LA MUERTE
===============================================
Somete a todas las estrategias al baño de sangre del 28 Feb - 1 Mar.
Flash Crash donde BTC se hundió, ADX llegó a 84, y V1 bloqueó 46 trades suicidas.

Pregunta: ¿Bollinger Bounce es un Santo Grial o una estrategia de días soleados?
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

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
    df['DC_MID'] = (df['DC_HI'] + df['DC_LO']) / 2
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
    return df

def v(r, c, d=0):
    x = r.get(c, d)
    return d if pd.isna(x) else x

def backtest(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0, risk=0.30,
             trailing=False, adapt_sl=False, verbose=False):
    cap = 10000; peak = 10000; dd = 0; pos = None; trades = []
    blocked = 0; signals = 0
    for i in range(202, len(df) - 1):
        r, p1, p2 = df.iloc[i], df.iloc[i - 1], df.iloc[i - 2]
        p3 = df.iloc[i - 3] if i >= 3 else p2
        if pos is None:
            if buy_fn(r, p1, p2, p3):
                signals += 1
                atr = v(r, 'ATR', 100)
                adx = v(r, 'ADX', 30)
                if adapt_sl:
                    sm = 2.5 if adx > 50 else 2.0 if adx > 35 else 1.5
                    tm = 4.0 if adx > 50 else 3.5 if adx > 35 else 3.0
                else:
                    sm = sl_m; tm = tp_m
                sz = min(cap * risk / r['close'], cap * 0.30 / r['close'])
                sl_px = r['close'] - sm * atr
                tp_px = r['close'] + tm * atr
                pos = {'e': r['close'], 'sl': sl_px, 'tp': tp_px,
                       'sz': sz, 'b': i, 'pk': r['close'],
                       'ts': r.name if hasattr(r, 'name') else i}
                if verbose:
                    print(f"     🟢 BUY  @ ${r['close']:.0f} | SL ${sl_px:.0f} | TP ${tp_px:.0f} | "
                          f"ADX {adx:.0f} | RSI {v(r,'RSI',50):.0f}")
        else:
            p = r['close']
            pos['pk'] = max(pos['pk'], p)
            if trailing and p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', 100))
            pnl = None; t = None
            if p <= pos['sl']:
                pnl = (pos['sl'] - pos['e']) * pos['sz']; t = 'SL'
            elif p >= pos['tp']:
                pnl = (pos['tp'] - pos['e']) * pos['sz']; t = 'TP'
            elif exit_fn(r, p1):
                pnl = (p - pos['e']) * pos['sz']; t = 'EXIT'
            if pnl is not None:
                cap += pnl; peak = max(peak, cap)
                dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 't': t, 'e': pos['e'], 'x': p,
                               'bars': i - pos['b'],
                               'pct': (pnl / (pos['e'] * pos['sz'])) * 100,
                               'ts': pos['ts']})
                if verbose:
                    e = "🟢" if pnl > 0 else "🔴"
                    print(f"     {e} {t:>4} @ ${p:.0f} | PnL ${pnl:+.2f} ({(pnl/(pos['e']*pos['sz']))*100:+.1f}%) | "
                          f"{(i-pos['b'])*5}min")
                pos = None
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']; cap += pnl
        trades.append({'pnl': pnl, 't': 'OPEN', 'e': pos['e'],
                       'x': df.iloc[-1]['close'], 'bars': 0,
                       'pct': (pnl / (pos['e'] * pos['sz'])) * 100,
                       'ts': pos.get('ts', '')})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    return {
        'name': name, 'n': len(trades), 'w': len(w), 'l': len(lo),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'avg_hold': np.mean([t['bars'] * 5 for t in trades]) if trades else 0,
        'max_win': max([t['pnl'] for t in w]) if w else 0,
        'max_loss': min([t['pnl'] for t in lo]) if lo else 0,
        'signals': signals, 'blocked': blocked,
        'details': trades
    }

# ═══ EXIT FUNCTIONS ═══
def exit_ema(r, p):
    return ((v(p, 'EMA9') >= v(p, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'))
            or r['close'] < v(r, 'EMA200') * 0.985)

def exit_bb(r, p):
    return v(r, 'BB_PCT') > 0.95 or exit_ema(r, p)

def exit_never(r, p):
    return False

def exit_donchian(r, p):
    return r['close'] <= v(r, 'DC_MID')

# ═══ STRATEGIES ═══

def buy_original(r, p1, p2, p3):
    """Original V1 — 4 Laws Strict"""
    return (r['close'] > v(r, 'EMA200') and v(r, 'ADX') > 20 and
            r['volume'] > v(r, 'VSMA') and v(p1, 'RSI') < 35 and v(r, 'RSI') > v(p1, 'RSI'))

def buy_momentum(r, p1, p2, p3):
    """Momentum V2"""
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX')
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']:
        return True
    atr_pct = (v(r, 'ATR', 100) / r['close']) * 100
    hv = atr_pct > 0.5
    rt = 40 if hv else 35; at = 15 if hv else 20; mt = 0.02 if hv else 0.01
    return (r['close'] > v(r, 'EMA200') * (1 - mt) and adx > at and
            r['volume'] > v(r, 'VSMA') * 0.8 and prsi < rt and rsi > prsi and prsi > p2rsi)

def buy_v21(r, p1, p2, p3):
    """V2.1 Production (Momentum+Trailing)"""
    return buy_momentum(r, p1, p2, p3)

def buy_bollinger(r, p1, p2, p3):
    """Bollinger Bounce — the candidate"""
    bb = v(r, 'BB_PCT', 0.5)
    rsi = v(r, 'RSI', 50)
    prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX')
    macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro

def buy_bollinger_hardened(r, p1, p2, p3):
    """Bollinger Hardened — con filtro anti-crash"""
    bb = v(r, 'BB_PCT', 0.5)
    rsi = v(r, 'RSI', 50)
    prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX')
    macro = r['close'] > v(r, 'EMA200') * 0.99
    # FILTRO ANTI-TORMENTA: Si ADX > 50, el mercado está en pánico → NO DISPARAR
    if adx > 50:
        return False
    # FILTRO EMA200: Si el precio cruza por debajo de EMA200, nos apartamos
    if r['close'] < v(r, 'EMA200'):
        return False
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15

def buy_ultimate(r, p1, p2, p3):
    """Ultimate V2"""
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX'); atr = v(r, 'ATR', 100)
    atr_pct = (atr / r['close']) * 100; hv = atr_pct > 0.5
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']:
        return True
    rsi_t = 43 if hv else 38; adx_t = 15 if hv else 20; mt = 0.02 if hv else 0.01
    marea = r['close'] > v(r, 'EMA200') * (1 - mt)
    fuerza = adx > adx_t; ballenas = r['volume'] > v(r, 'VSMA') * 0.8
    pb = prsi < rsi_t and rsi > prsi; mom = rsi > prsi and prsi > p2rsi
    bb = v(r, 'BB_PCT', 0.5) < 0.35
    return marea and fuerza and ballenas and pb and mom and bb

def buy_squeeze(r, p1, p2, p3):
    """BB Squeeze Breakout"""
    width = v(r, 'BB_WIDTH', 5)
    pwidth = v(p1, 'BB_WIDTH', 5)
    squeeze = pwidth < 2.0
    breakout = r['close'] > v(r, 'BB_HI') * 0.998
    trend = r['close'] > v(r, 'EMA200')
    adx_rising = v(r, 'ADX') > v(p1, 'ADX') and v(r, 'ADX') > 20
    return squeeze and breakout and trend and adx_rising

async def main():
    print("=" * 75)
    print("💀 CT4 LAB — LA MÁQUINA DEL TIEMPO DE LA MUERTE")
    print("   Flash Crash 28 Feb - 1 Mar 2026")
    print("=" * 75)

    exchange = ccxt.binance({'sandbox': True})

    # ═══ PHASE 1: Load crash data (Feb 28 - Mar 1) ═══
    # We need data from ~Feb 27 (for EMA200 warmup) through Mar 1
    # Fetch multiple batches to cover the full period
    
    # Start from Feb 26 00:00 UTC to get enough warmup data
    start_ts = int(datetime(2026, 2, 26, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    
    all_candles = []
    since = start_ts
    for batch in range(4):  # 4 batches × 1000 = 4000 candles = ~14 days
        candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=1000)
        if not candles:
            break
        all_candles.extend(candles)
        since = candles[-1][0] + 1  # Next ms after last candle
        print(f"  📥 Batch {batch+1}: {len(candles)} velas cargadas")
        await asyncio.sleep(0.5)  # Rate limit grace
    
    await exchange.close()
    
    # Remove duplicates
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    
    df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df.sort_index()
    df = calc(df)
    
    # ═══ MARKET ANALYSIS ═══
    total_hrs = len(df) * 5 / 60
    crash_zone = df.loc['2026-02-28':'2026-03-01'] if '2026-02-28' in df.index.strftime('%Y-%m-%d').unique() else df
    
    print(f"\n📊 DATOS CARGADOS:")
    print(f"   Total:    {len(df)} velas ({total_hrs:.0f}h)")
    print(f"   Período:  {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")
    print(f"   Máximo:   ${df['close'].max():.0f}")
    print(f"   Mínimo:   ${df['close'].min():.0f}")
    print(f"   Rango:    ${df['close'].max() - df['close'].min():.0f}")
    
    # Find the crash
    max_price = df['close'].max()
    min_price = df['close'].min()
    max_adx = df['ADX'].max()
    min_rsi = df['RSI'].min()
    max_idx = df['close'].idxmax()
    min_idx = df['close'].idxmin()
    crash_pct = (min_price - max_price) / max_price * 100
    
    print(f"\n💀 ANATOMÍA DEL CRASH:")
    print(f"   Cima:     ${max_price:.0f} ({max_idx.strftime('%m/%d %H:%M')})")
    print(f"   Suelo:    ${min_price:.0f} ({min_idx.strftime('%m/%d %H:%M')})")
    print(f"   Caída:    {crash_pct:.1f}%")
    print(f"   ADX Max:  {max_adx:.0f}")
    print(f"   RSI Min:  {min_rsi:.0f}")
    
    # B&H for this period
    bh_start = df.iloc[202]['close']
    bh_end = df.iloc[-1]['close']
    bh_ret = (bh_end - bh_start) / bh_start * 100
    bh_pnl = 10000 * bh_ret / 100
    print(f"   B&H:      {bh_ret:+.1f}% (${bh_pnl:+.0f})")
    
    # ═══ RUN ALL STRATEGIES ═══
    print(f"\n{'=' * 75}")
    print("🔥 EJECUTANDO ESTRATEGIAS EN LA ZONA DE MUERTE")
    print(f"{'=' * 75}")
    
    configs = [
        ("A. ORIGINAL V1",            buy_original,        exit_ema,  1.5, 3.0, False, False),
        ("B. MOMENTUM V2",            buy_momentum,        exit_ema,  1.5, 3.0, False, False),
        ("C. V2.1 PRODUCCIÓN ★",      buy_v21,             exit_ema,  1.5, 3.0, True,  False),
        ("D. BOLLINGER BOUNCE",       buy_bollinger,       exit_bb,   1.5, 3.0, True,  False),
        ("E. BOLLINGER HARDENED 🛡️",  buy_bollinger_hardened, exit_bb, 1.5, 3.0, True,  False),
        ("F. BB SQUEEZE",             buy_squeeze,         exit_never,1.5, 3.0, False, False),
        ("G. ULTIMATE V2",            buy_ultimate,        exit_ema,  1.5, 3.0, True,  True),
    ]
    
    results = []
    for name, buy, exit_fn, sl, tp, trail, adapt in configs:
        print(f"\n  ⚔️  {name}")
        r = backtest(df, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt, verbose=True)
        results.append(r)
        if r['n'] == 0:
            print(f"     🤫 SILENCIO TOTAL — 0 trades. Francotirador no disparó.")
        else:
            e = "🟢" if r['pnl'] > 0 else "🔴"
            print(f"     {e} Resultado: {r['n']} trades | WR {r['wr']:.0f}% | "
                  f"PnL ${r['pnl']:+.2f} | DD {r['dd']:.1f}%")
    
    # B&H ref
    results.append({
        'name': 'H. BUY & HOLD', 'n': 1,
        'w': 1 if bh_pnl > 0 else 0, 'l': 0 if bh_pnl > 0 else 1,
        'wr': 100 if bh_pnl > 0 else 0, 'pnl': bh_pnl, 'dd': abs(crash_pct),
        'cap': 10000 + bh_pnl, 'pf': 999, 'avg_hold': total_hrs * 60,
        'max_win': bh_pnl, 'max_loss': 0, 'signals': 1, 'blocked': 0, 'details': []
    })
    
    # ═══ COMPARISON TABLE ═══
    print(f"\n{'=' * 75}")
    print("📊 RESULTADOS: ZONA DE MUERTE")
    print(f"{'=' * 75}")
    print(f"   {'Estrategia':<30} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   " + "-" * 68)
    for r in results:
        e = "🟢" if r['pnl'] > 0 else ("🔴" if r['pnl'] < 0 else "⚪")
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<28} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {pf:>5}")
    
    # ═══ RANKING ═══
    ranked = sorted(results, key=lambda x: x['pnl'], reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i+4}." for i in range(5)]
    print(f"\n{'=' * 75}")
    print("🏆 RANKING EN LA TORMENTA")
    print(f"{'=' * 75}")
    for i, r in enumerate(ranked):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        bar = "█" * max(1, int(max(0, r['pnl']) / 10))
        neg_bar = "▓" * max(0, int(abs(min(0, r['pnl'])) / 10))
        print(f"  {medals[i]} {e} {r['name']:<30} ${r['pnl']:>+8.2f}  {bar}{neg_bar}")
    
    # ═══ VERDICT ═══
    bb = next(r for r in results if 'BOLLINGER BOUNCE' in r['name'])
    bbh = next(r for r in results if 'HARDENED' in r['name'])
    v21 = next(r for r in results if 'PRODUCCIÓN' in r['name'] or 'V2.1' in r['name'])
    
    print(f"\n{'=' * 75}")
    print("⚖️  EL VEREDICTO")
    print(f"{'=' * 75}")
    print(f"  Bollinger Bounce:    ${bb['pnl']:>+8.2f} | {bb['n']} trades | WR {bb['wr']:.0f}% | DD {bb['dd']:.1f}%")
    print(f"  Bollinger Hardened:  ${bbh['pnl']:>+8.2f} | {bbh['n']} trades | WR {bbh['wr']:.0f}% | DD {bbh['dd']:.1f}%")
    print(f"  V2.1 Producción:     ${v21['pnl']:>+8.2f} | {v21['n']} trades | WR {v21['wr']:.0f}% | DD {v21['dd']:.1f}%")
    
    if bb['pnl'] > 0 and bb['dd'] < 2:
        print("\n  🏆 BOLLINGER BOUNCE SOBREVIVIÓ AL CRASH")
        print("     → Es un SANTO GRIAL potencial. Funciona en sol y tormenta.")
    elif bb['n'] == 0:
        print("\n  🤫 BOLLINGER BOUNCE SE MANTUVO AL MARGEN")
        print("     → Las reglas de EMA200+RSI la protegieron. No disparó en la tormenta.")
        print("     → Esto es BUENO: no pierde dinero cuando no debe operar.")
    elif bb['pnl'] < 0 and bbh['pnl'] >= bb['pnl']:
        print("\n  🛡️ BOLLINGER BOUNCE NECESITA BLINDAJE")
        print(f"     → Original: ${bb['pnl']:+.2f} (quemó dinero)")
        print(f"     → Hardened: ${bbh['pnl']:+.2f} (con filtro ADX<50 + EMA200)")
        improvement = bbh['pnl'] - bb['pnl']
        print(f"     → El filtro anti-tormenta salvó ${improvement:+.2f}")
    else:
        print("\n  🔴 BOLLINGER BOUNCE QUEMÓ LA CUENTA")
        print("     → Es una estrategia de DÍAS SOLEADOS.")
        print("     → Necesita filtros agresivos o descartarla.")

if __name__ == "__main__":
    asyncio.run(main())
