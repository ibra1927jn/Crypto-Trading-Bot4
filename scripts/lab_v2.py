"""
CT4 Lab V2 — Extended Strategy Research
==========================================
Tests 10 strategies against max available data (1000 candles = ~83h).
Includes the current V2.1 (Momentum+Trailing with 30% cap) + 4 new strategies.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

def calc(df):
    c, h, lo = df['close'], df['high'], df['low']
    df['EMA9'] = c.ewm(span=9).mean()
    df['EMA21'] = c.ewm(span=21).mean()
    df['EMA50'] = c.ewm(span=50).mean()
    df['EMA200'] = c.ewm(span=200).mean()
    # RSI
    d = c.diff()
    g = d.where(d > 0, 0).rolling(14).mean()
    l = (-d.where(d < 0, 0)).rolling(14).mean()
    rs = g / l.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    # ATR
    tr = pd.concat([h - lo, abs(h - c.shift(1)), abs(lo - c.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    # ADX
    pdm = h.diff().where(lambda x: (x > 0) & (x > -lo.diff()), 0)
    mdm = (-lo.diff()).where(lambda x: (x > 0) & (x > h.diff()), 0)
    pdi = 100 * (pdm.rolling(14).mean() / df['ATR'])
    mdi = 100 * (mdm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['+DI'] = pdi
    df['-DI'] = mdi
    # Volume
    df['VSMA'] = df['volume'].rolling(20).mean()
    # Bollinger Bands
    bb_mid = c.rolling(20).mean()
    bs = c.rolling(20).std()
    df['BB_MID'] = bb_mid
    df['BB_LO'] = bb_mid - 2 * bs
    df['BB_HI'] = bb_mid + 2 * bs
    df['BB_PCT'] = (c - df['BB_LO']) / (df['BB_HI'] - df['BB_LO'] + 1e-10)
    df['BB_WIDTH'] = (df['BB_HI'] - df['BB_LO']) / bb_mid * 100
    # Donchian
    df['DC_HI'] = h.rolling(20).max()
    df['DC_LO'] = lo.rolling(20).min()
    df['DC_MID'] = (df['DC_HI'] + df['DC_LO']) / 2
    # MACD
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_S'] = df['MACD'].ewm(span=9).mean()
    df['MACD_H'] = df['MACD'] - df['MACD_S']
    # Stochastic RSI
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

def backtest(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0, risk=0.30, trailing=False, adapt_sl=False):
    """Backtest with 30% exposure cap (matching V2.1 production code)."""
    cap = 10000
    peak = 10000
    dd = 0
    pos = None
    trades = []
    for i in range(202, len(df) - 1):
        r, p1, p2 = df.iloc[i], df.iloc[i - 1], df.iloc[i - 2]
        p3 = df.iloc[i - 3] if i >= 3 else p2
        if pos is None:
            if buy_fn(r, p1, p2, p3):
                atr = v(r, 'ATR', 100)
                adx = v(r, 'ADX', 30)
                if adapt_sl:
                    sm = 2.5 if adx > 50 else 2.0 if adx > 35 else 1.5
                    tm = 4.0 if adx > 50 else 3.5 if adx > 35 else 3.0
                else:
                    sm = sl_m
                    tm = tp_m
                # 30% cap (same as production V2.1)
                sz = min(cap * risk / r['close'], cap * 0.30 / r['close'])
                sl_px = r['close'] - sm * atr
                tp_px = r['close'] + tm * atr
                pos = {'e': r['close'], 'sl': sl_px, 'tp': tp_px,
                       'sz': sz, 'b': i, 'pk': r['close']}
        else:
            p = r['close']
            pos['pk'] = max(pos['pk'], p)
            if trailing and p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', 100))
            pnl = None
            t = None
            if p <= pos['sl']:
                pnl = (pos['sl'] - pos['e']) * pos['sz']; t = 'SL'
            elif p >= pos['tp']:
                pnl = (pos['tp'] - pos['e']) * pos['sz']; t = 'TP'
            elif exit_fn(r, p1):
                pnl = (p - pos['e']) * pos['sz']; t = 'EXIT'
            if pnl is not None:
                cap += pnl
                peak = max(peak, cap)
                dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 't': t, 'e': pos['e'], 'x': p,
                               'bars': i - pos['b'],
                               'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
                pos = None
    # Close any open position at end
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']
        cap += pnl
        trades.append({'pnl': pnl, 't': 'OPEN', 'e': pos['e'],
                       'x': df.iloc[-1]['close'], 'bars': 0,
                       'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
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
        'details': trades
    }

# ═══════════════════════════════════════════════
# EXIT FUNCTIONS
# ═══════════════════════════════════════════════

def exit_ema(r, p):
    """Exit on EMA9<EMA21 cross or loss of EMA200."""
    return ((v(p, 'EMA9') >= v(p, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'))
            or r['close'] < v(r, 'EMA200') * 0.985)

def exit_donchian(r, p):
    return r['close'] <= v(r, 'DC_MID')

def exit_macd(r, p):
    """Exit on MACD bearish cross."""
    return v(p, 'MACD') >= v(p, 'MACD_S') and v(r, 'MACD') < v(r, 'MACD_S')

def exit_bb(r, p):
    """Exit when price hits upper Bollinger or EMA cross."""
    return v(r, 'BB_PCT') > 0.95 or exit_ema(r, p)

def exit_never(r, p):
    """Never exit by signal — rely only on SL/TP."""
    return False

# ═══════════════════════════════════════════════
# STRATEGY ENTRY FUNCTIONS
# ═══════════════════════════════════════════════

# 1. ORIGINAL V1
def buy_original(r, p1, p2, p3):
    """A. Original V1 — Strict 4 Laws"""
    return (r['close'] > v(r, 'EMA200') and v(r, 'ADX') > 20 and
            r['volume'] > v(r, 'VSMA') and v(p1, 'RSI') < 35 and v(r, 'RSI') > v(p1, 'RSI'))

# 2. MOMENTUM V2 (current production)
def buy_momentum(r, p1, p2, p3):
    """B. Momentum Adaptativa V2"""
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX')
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']:
        return True
    atr_pct = (v(r, 'ATR', 100) / r['close']) * 100
    hv = atr_pct > 0.5
    rt = 40 if hv else 35
    at = 15 if hv else 20
    mt = 0.02 if hv else 0.01
    return (r['close'] > v(r, 'EMA200') * (1 - mt) and adx > at and
            r['volume'] > v(r, 'VSMA') * 0.8 and prsi < rt and rsi > prsi and prsi > p2rsi)

# 3. MOMENTUM + TRAILING (V2.1 = production)
def buy_v21(r, p1, p2, p3):
    """C. V2.1 PRODUCCIÓN (Momentum+Trailing+30%cap)"""
    return buy_momentum(r, p1, p2, p3)

# 4. BOLLINGER BOUNCE
def buy_bollinger(r, p1, p2, p3):
    """D. Bollinger Bounce — Buy when price touches lower band + RSI oversold"""
    bb = v(r, 'BB_PCT', 0.5)
    rsi = v(r, 'RSI', 50)
    prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX')
    macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro

# 5. MACD MOMENTUM
def buy_macd(r, p1, p2, p3):
    """E. MACD Cross + Trend — Buy on bullish MACD cross in uptrend"""
    macd_cross = v(p1, 'MACD') < v(p1, 'MACD_S') and v(r, 'MACD') >= v(r, 'MACD_S')
    hist_rising = v(r, 'MACD_H') > v(p1, 'MACD_H')
    trend_up = r['close'] > v(r, 'EMA50')
    vol = r['volume'] > v(r, 'VSMA') * 0.7
    return macd_cross and hist_rising and trend_up and vol

# 6. STOCHASTIC RSI OVERSOLD
def buy_stoch_rsi(r, p1, p2, p3):
    """F. Stochastic RSI — Buy when StochRSI crosses up from oversold"""
    sk = v(r, 'SRSI_K', 50)
    sd = v(r, 'SRSI_D', 50)
    psk = v(p1, 'SRSI_K', 50)
    cross_up = psk < sd and sk >= sd
    oversold = psk < 25
    trend = r['close'] > v(r, 'EMA200') * 0.99
    adx = v(r, 'ADX') > 15
    return cross_up and oversold and trend and adx

# 7. DONCHIAN TURTLE
def buy_donchian(r, p1, p2, p3):
    """G. Donchian Turtle — Breakout on new high"""
    new_high = r['close'] >= v(r, 'DC_HI') * 0.999
    vol_confirm = r['volume'] > v(r, 'VSMA')
    trend = v(r, 'ADX') > 20
    return new_high and vol_confirm and trend

# 8. BOLLINGER SQUEEZE BREAKOUT
def buy_squeeze(r, p1, p2, p3):
    """H. BB Squeeze Breakout — Low vol followed by breakout"""
    width = v(r, 'BB_WIDTH', 5)
    pwidth = v(p1, 'BB_WIDTH', 5)
    squeeze = pwidth < 2.0  # Bands were tight
    breakout = r['close'] > v(r, 'BB_HI') * 0.998
    trend = r['close'] > v(r, 'EMA200')
    adx_rising = v(r, 'ADX') > v(p1, 'ADX') and v(r, 'ADX') > 20
    return squeeze and breakout and trend and adx_rising

# 9. TRIPLE CONFIRMATION (EMA cross + RSI + Volume)
def buy_triple(r, p1, p2, p3):
    """I. Triple Confirm — EMA9>21 cross + RSI rising + Volume spike"""
    ema_cross = v(p1, 'EMA9') <= v(p1, 'EMA21') and v(r, 'EMA9') > v(r, 'EMA21')
    rsi_ok = 30 < v(r, 'RSI', 50) < 60
    vol_spike = r['volume'] > v(r, 'VSMA') * 1.2
    above_200 = r['close'] > v(r, 'EMA200')
    return ema_cross and rsi_ok and vol_spike and above_200

# 10. ULTIMATE V2 (everything combined)
def buy_ultimate(r, p1, p2, p3):
    """J. ULTIMATE V2 — All signals combined"""
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX')
    atr = v(r, 'ATR', 100)
    atr_pct = (atr / r['close']) * 100
    hv = atr_pct > 0.5
    # Override
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']:
        return True
    rsi_t = 43 if hv else 38
    adx_t = 15 if hv else 20
    mt = 0.02 if hv else 0.01
    marea = r['close'] > v(r, 'EMA200') * (1 - mt)
    fuerza = adx > adx_t
    ballenas = r['volume'] > v(r, 'VSMA') * 0.8
    pb = prsi < rsi_t and rsi > prsi
    mom = rsi > prsi and prsi > p2rsi
    bb = v(r, 'BB_PCT', 0.5) < 0.35
    return marea and fuerza and ballenas and pb and mom and bb

# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

async def main():
    print("=" * 75)
    print("🔬 CT4 LAB V2 — Investigación Estratégica (10 Estrategias)")
    print("=" * 75)

    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', limit=1000)
    await exchange.close()

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)
    hrs = len(df) * 5 / 60

    print(f"\n✅ {len(df)} velas ({hrs:.0f}h)")
    print(f"   Período: {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")
    print(f"   Rango:   ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    bh_ret = (df.iloc[-1]['close'] - df.iloc[200]['close']) / df.iloc[200]['close'] * 100
    bh_pnl = 10000 * bh_ret / 100
    print(f"   B&H:     {bh_ret:+.2f}% (${bh_pnl:+.0f})")
    print(f"   Cap:     30% max exposure (same as production)")

    configs = [
        ("A. ORIGINAL V1",            buy_original,  exit_ema,      1.5, 3.0, False, False),
        ("B. MOMENTUM V2",            buy_momentum,  exit_ema,      1.5, 3.0, False, False),
        ("C. V2.1 PRODUCCIÓN ★",      buy_v21,       exit_ema,      1.5, 3.0, True,  False),
        ("D. BOLLINGER BOUNCE",       buy_bollinger, exit_bb,       1.5, 3.0, True,  False),
        ("E. MACD MOMENTUM",          buy_macd,      exit_macd,     1.5, 3.0, False, False),
        ("F. STOCHASTIC RSI",         buy_stoch_rsi, exit_ema,      1.5, 3.0, True,  False),
        ("G. DONCHIAN TURTLE",        buy_donchian,  exit_donchian, 1.5, 3.0, False, False),
        ("H. BB SQUEEZE BREAKOUT",    buy_squeeze,   exit_never,    1.5, 3.0, False, False),
        ("I. TRIPLE CONFIRM",         buy_triple,    exit_ema,      1.5, 3.0, True,  False),
        ("J. ULTIMATE V2",            buy_ultimate,  exit_ema,      1.5, 3.0, True,  True),
    ]

    results = []
    for name, buy, exit_fn, sl, tp, trail, adapt in configs:
        r = backtest(df, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt)
        results.append(r)

    # Buy & Hold reference
    results.append({
        'name': 'K. BUY & HOLD (ref)', 'n': 1,
        'w': 1 if bh_pnl > 0 else 0, 'l': 0 if bh_pnl > 0 else 1,
        'wr': 100 if bh_pnl > 0 else 0, 'pnl': bh_pnl, 'dd': 0,
        'cap': 10000 + bh_pnl, 'pf': 999, 'avg_hold': hrs * 60,
        'max_win': bh_pnl, 'max_loss': 0, 'details': []
    })

    # ═══ RESULTS TABLE ═══
    print(f"\n{'=' * 75}")
    print(f"📊 RESULTADOS ({len(results)} estrategias)")
    print(f"{'=' * 75}")
    print(f"   {'Estrategia':<30} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5} {'AvgMin':>6}")
    print("   " + "-" * 72)
    for r in results:
        e = "🟢" if r['pnl'] > 0 else ("🔴" if r['pnl'] < 0 else "⚪")
        print(f"   {e} {r['name']:<28} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% "
              f"{r['pf']:>5.1f} {r['avg_hold']:>5.0f}m")

    # ═══ RANKING ═══
    ranked = sorted(results, key=lambda x: x['pnl'], reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i+4}." for i in range(8)]
    print(f"\n{'=' * 75}")
    print("🏆 RANKING POR PnL")
    print(f"{'=' * 75}")
    for i, r in enumerate(ranked):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        bar = "█" * max(1, int(max(0, r['pnl']) / 15))
        print(f"  {medals[i]} {e} {r['name']:<30} ${r['pnl']:>+8.2f}  {bar}")

    # ═══ RISK-ADJUSTED TABLE ═══
    print(f"\n{'=' * 75}")
    print("🛡️ ANÁLISIS RIESGO-RECOMPENSA")
    print(f"{'=' * 75}")
    print(f"   {'Estrategia':<30} {'PnL':>8} {'DD%':>5} {'PnL/DD':>7} {'Sharpe':>7} {'PF':>5}")
    print("   " + "-" * 65)
    for r in ranked:
        pnl_dd = r['pnl'] / r['dd'] if r['dd'] > 0 else 999
        sharpe = r['pnl'] / abs(r['max_loss']) if r['max_loss'] != 0 else 999
        print(f"   {r['name']:<30} ${r['pnl']:>+6.0f} {r['dd']:>4.1f}% "
              f"{pnl_dd:>+6.1f} {sharpe:>+6.1f} {r['pf']:>5.1f}")

    # ═══ TRADE DETAILS top 3 ═══
    print(f"\n{'=' * 75}")
    print("📋 DETALLE DE TRADES — Top 3")
    print(f"{'=' * 75}")
    for r in ranked[:3]:
        if not r['details']:
            continue
        print(f"\n  📌 {r['name']}")
        print(f"     Trades: {r['n']} | W:{r['w']} L:{r['l']} | WR: {r['wr']:.0f}% | PF: {r['pf']:.1f}")
        print(f"     MaxWin: ${r['max_win']:+.2f} | MaxLoss: ${r['max_loss']:+.2f}")
        for j, t in enumerate(r['details'][:10]):
            e = "🟢" if t['pnl'] > 0 else "🔴"
            print(f"     {e} #{j+1} ${t['e']:.0f}→${t['x']:.0f} | {t['t']:>4} | "
                  f"${t['pnl']:>+7.2f} ({t['pct']:>+5.1f}%) | {t['bars']*5}min")
        if len(r['details']) > 10:
            print(f"     ... +{len(r['details'])-10} trades más")

    # ═══ PRODUCTION COMPARISON ═══
    print(f"\n{'=' * 75}")
    print("⚡ V2.1 PRODUCCIÓN vs MEJOR ALTERNATIVA")
    print(f"{'=' * 75}")
    v21 = next(r for r in results if '2.1' in r['name'] or 'PRODUCCIÓN' in r['name'])
    best = ranked[0]
    print(f"  V2.1 actual:      ${v21['pnl']:>+8.2f} | {v21['n']} trades | {v21['wr']:.0f}% WR | DD {v21['dd']:.1f}%")
    print(f"  Mejor ({best['name'][:20]}): ${best['pnl']:>+8.2f} | {best['n']} trades | {best['wr']:.0f}% WR | DD {best['dd']:.1f}%")
    if v21 == best or v21['name'] == best['name']:
        print("  ✅ V2.1 ES la mejor estrategia encontrada")
    else:
        diff = best['pnl'] - v21['pnl']
        print(f"  📊 Diferencia: ${diff:+.2f} — Mejor alternativa supera por ${abs(diff):.2f}")

if __name__ == "__main__":
    asyncio.run(main())
