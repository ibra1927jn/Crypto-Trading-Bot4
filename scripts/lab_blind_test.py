"""
CT4 LAB — TEST CIEGO (Walk-Forward)
=====================================
Las estrategias fueron DISEÑADAS con datos del 26 Feb - 1 Mar.
Ahora las sometemos a datos que NUNCA HEMOS VISTO.

Split:
  IN-SAMPLE  (entrenamiento):  Feb 26 → Mar 2   ← Aquí se diseñaron
  OUT-OF-SAMPLE (ciego):       Mar 2 → Mar 5    ← Nunca visto

Si una estrategia gana en IN-SAMPLE pero pierde en OUT-OF-SAMPLE,
está sobreajustada (overfitting). Solo las que ganan en AMBOS son reales.
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

def backtest(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0,
             trailing=False, adapt_sl=False):
    cap = 10000; peak = 10000; dd = 0; pos = None; trades = []
    for i in range(202, len(df) - 1):
        r, p1, p2 = df.iloc[i], df.iloc[i - 1], df.iloc[i - 2]
        p3 = df.iloc[i - 3] if i >= 3 else p2
        if pos is None:
            if buy_fn(r, p1, p2, p3):
                atr = v(r, 'ATR', 100); adx = v(r, 'ADX', 30)
                if adapt_sl:
                    sm = 2.5 if adx > 50 else 2.0 if adx > 35 else 1.5
                    tm = 4.0 if adx > 50 else 3.5 if adx > 35 else 3.0
                else:
                    sm = sl_m; tm = tp_m
                sz = min(cap * 0.30 / r['close'], cap * 0.30 / r['close'])
                pos = {'e': r['close'], 'sl': r['close'] - sm * atr,
                       'tp': r['close'] + tm * atr, 'sz': sz, 'b': i, 'pk': r['close']}
        else:
            p = r['close']; pos['pk'] = max(pos['pk'], p)
            if trailing and p > pos['e'] * 1.005:
                pos['sl'] = max(pos['sl'], p - 1.0 * v(r, 'ATR', 100))
            pnl = None; t = None
            if p <= pos['sl']: pnl = (pos['sl'] - pos['e']) * pos['sz']; t = 'SL'
            elif p >= pos['tp']: pnl = (pos['tp'] - pos['e']) * pos['sz']; t = 'TP'
            elif exit_fn(r, p1): pnl = (p - pos['e']) * pos['sz']; t = 'EXIT'
            if pnl is not None:
                cap += pnl; peak = max(peak, cap); dd = max(dd, (peak - cap) / peak * 100)
                trades.append({'pnl': pnl, 't': t, 'e': pos['e'], 'x': p,
                               'bars': i - pos['b'],
                               'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
                pos = None
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']; cap += pnl
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
def exit_macd(r, p):
    return v(p, 'MACD') >= v(p, 'MACD_S') and v(r, 'MACD') < v(r, 'MACD_S')

# ═══ STRATEGIES ═══
def buy_original(r, p1, p2, p3):
    return (r['close'] > v(r, 'EMA200') and v(r, 'ADX') > 20 and
            r['volume'] > v(r, 'VSMA') and v(p1, 'RSI') < 35 and v(r, 'RSI') > v(p1, 'RSI'))

def buy_momentum(r, p1, p2, p3):
    rsi, prsi, p2rsi = v(r, 'RSI', 50), v(p1, 'RSI', 50), v(p2, 'RSI', 50)
    adx = v(r, 'ADX')
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']: return True
    atr_pct = (v(r, 'ATR', 100) / r['close']) * 100; hv = atr_pct > 0.5
    rt = 40 if hv else 35; at = 15 if hv else 20; mt = 0.02 if hv else 0.01
    return (r['close'] > v(r, 'EMA200') * (1 - mt) and adx > at and
            r['volume'] > v(r, 'VSMA') * 0.8 and prsi < rt and rsi > prsi and prsi > p2rsi)

def buy_v21(r, p1, p2, p3):
    return buy_momentum(r, p1, p2, p3)

def buy_bollinger(r, p1, p2, p3):
    bb = v(r, 'BB_PCT', 0.5); rsi = v(r, 'RSI', 50); prsi = v(p1, 'RSI', 50)
    adx = v(r, 'ADX'); macro = r['close'] > v(r, 'EMA200') * 0.99
    return bb < 0.15 and prsi < 35 and rsi > prsi and adx > 15 and macro

def buy_squeeze(r, p1, p2, p3):
    width = v(r, 'BB_WIDTH', 5); pwidth = v(p1, 'BB_WIDTH', 5)
    squeeze = pwidth < 2.0; breakout = r['close'] > v(r, 'BB_HI') * 0.998
    trend = r['close'] > v(r, 'EMA200')
    adx_rising = v(r, 'ADX') > v(p1, 'ADX') and v(r, 'ADX') > 20
    return squeeze and breakout and trend and adx_rising

def buy_macd(r, p1, p2, p3):
    macd_cross = v(p1, 'MACD') < v(p1, 'MACD_S') and v(r, 'MACD') >= v(r, 'MACD_S')
    hist_rising = v(r, 'MACD_H') > v(p1, 'MACD_H')
    trend_up = r['close'] > v(r, 'EMA50')
    vol = r['volume'] > v(r, 'VSMA') * 0.7
    return macd_cross and hist_rising and trend_up and vol

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

async def main():
    print("=" * 80)
    print("🔬 CT4 LAB — TEST CIEGO (Walk-Forward Out-of-Sample)")
    print("=" * 80)
    print()
    print("  Las estrategias se DISEÑARON con datos del 26 Feb - 1 Mar.")
    print("  Ahora las enfrentamos a datos que NUNCA hemos visto.")
    print("  Si pierden aquí pero ganaron antes → OVERFITTING (falsa confianza).")
    print("  Si ganan aquí → LA ESTRATEGIA ES REAL.")

    exchange = ccxt.binance({'sandbox': True})

    # ═══ Load ALL data: Feb 24 → now ═══
    start_ts = int(datetime(2026, 2, 24, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    all_candles = []
    since = start_ts
    for batch in range(5):
        candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=1000)
        if not candles: break
        all_candles.extend(candles)
        since = candles[-1][0] + 1
        print(f"  📥 Batch {batch+1}: {len(candles)} velas")
        await asyncio.sleep(0.5)
    await exchange.close()

    seen = set(); unique = []
    for c in all_candles:
        if c[0] not in seen: seen.add(c[0]); unique.append(c)

    df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df.sort_index()
    df = calc(df)

    print(f"\n  Total: {len(df)} velas ({len(df)*5/60:.0f}h)")
    print(f"  Rango: {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")

    # ═══ SPLIT: In-Sample vs Out-of-Sample ═══
    # Cut point: Mar 2 00:00 UTC
    cut_date = '2026-03-02'
    
    # For indicators, we calculate on ALL data (EMA200 needs warmup)
    # But we only count trades that happen in their respective windows
    
    # Find indices for the cut
    cut_idx = None
    for i, ts in enumerate(df.index):
        if ts.strftime('%Y-%m-%d') >= cut_date:
            cut_idx = i
            break
    
    if cut_idx is None or cut_idx < 250:
        print(f"\n  ❌ No hay suficientes datos para split. cut_idx={cut_idx}")
        return

    # In-sample: everything before Mar 2
    df_in = df.iloc[:cut_idx].copy()
    # Out-of-sample: Mar 2 onwards (but needs warmup → use full df, filter trades by index)
    df_out = df.iloc[max(0, cut_idx-250):].copy()  # 250 candles warmup for EMA200
    # recalculate indicators for out-of-sample slice
    df_out = calc(df_out)
    
    in_hrs = len(df_in) * 5 / 60
    out_hrs = (len(df) - cut_idx) * 5 / 60
    
    print(f"\n  ═══ SPLIT ═══")
    print(f"  IN-SAMPLE  (entrenamiento): {df_in.index[0].strftime('%m/%d')} → {df_in.index[-1].strftime('%m/%d')} | {len(df_in)} velas ({in_hrs:.0f}h)")
    print(f"  OUT-OF-SAMPLE (ciego):      {df.index[cut_idx].strftime('%m/%d')} → {df.index[-1].strftime('%m/%d')} | {len(df)-cut_idx} velas ({out_hrs:.0f}h)")
    
    # B&H for both periods
    bh_in_start = df_in.iloc[202]['close']
    bh_in_end = df_in.iloc[-1]['close']
    bh_in = (bh_in_end - bh_in_start) / bh_in_start * 100
    
    bh_out_start = df_out.iloc[202]['close'] if len(df_out) > 202 else df_out.iloc[0]['close']
    bh_out_end = df_out.iloc[-1]['close']
    bh_out = (bh_out_end - bh_out_start) / bh_out_start * 100
    
    print(f"  B&H In-Sample:              {bh_in:+.1f}%")
    print(f"  B&H Out-of-Sample:          {bh_out:+.1f}%")
    
    # ═══ Strategies ═══
    configs = [
        ("A. ORIGINAL V1",         buy_original,   exit_ema,      1.5, 3.0, False, False),
        ("B. MOMENTUM V2",         buy_momentum,   exit_ema,      1.5, 3.0, False, False),
        ("C. V2.1 PRODUCCIÓN ★",   buy_v21,        exit_ema,      1.5, 3.0, True,  False),
        ("D. BOLLINGER BOUNCE",    buy_bollinger,   exit_bb,       1.5, 3.0, True,  False),
        ("E. BB SQUEEZE",          buy_squeeze,     exit_never,    1.5, 3.0, False, False),
        ("F. MACD MOMENTUM",       buy_macd,        exit_macd,     1.5, 3.0, False, False),
        ("G. STOCHASTIC RSI",      buy_stoch_rsi,   exit_ema,      1.5, 3.0, True,  False),
        ("H. ULTIMATE V2",         buy_ultimate,    exit_ema,      1.5, 3.0, True,  True),
    ]
    
    # ═══ RUN ON BOTH PERIODS ═══
    in_results = []
    out_results = []
    
    for name, buy, exit_fn, sl, tp, trail, adapt in configs:
        r_in = backtest(df_in, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt)
        r_out = backtest(df_out, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt)
        in_results.append(r_in)
        out_results.append(r_out)
    
    # ═══ IN-SAMPLE RESULTS ═══
    print(f"\n{'=' * 80}")
    print(f"📊 IN-SAMPLE — Datos conocidos (donde se diseñaron las estrategias)")
    print(f"{'=' * 80}")
    print(f"   {'Estrategia':<28} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   " + "-" * 65)
    for r in in_results:
        e = "🟢" if r['pnl'] > 0 else ("🔴" if r['pnl'] < 0 else "⚪")
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<26} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {pf:>5}")
    
    # ═══ OUT-OF-SAMPLE RESULTS ═══
    print(f"\n{'=' * 80}")
    print(f"🔮 OUT-OF-SAMPLE — Datos NUNCA VISTOS (test ciego)")
    print(f"{'=' * 80}")
    print(f"   {'Estrategia':<28} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   " + "-" * 65)
    for r in out_results:
        e = "🟢" if r['pnl'] > 0 else ("🔴" if r['pnl'] < 0 else "⚪")
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<26} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {pf:>5}")
    
    # ═══ WALK-FORWARD COMPARISON ═══
    print(f"\n{'=' * 80}")
    print(f"⚖️  WALK-FORWARD: ¿Sobrevive al test ciego?")
    print(f"{'=' * 80}")
    print(f"   {'Estrategia':<28} {'In-Sample':>10} {'Out-Sample':>10} {'Delta':>8} {'Verdict':>12}")
    print("   " + "-" * 75)
    
    for i_r, o_r in zip(in_results, out_results):
        delta = o_r['pnl'] - i_r['pnl']
        # Verdict logic
        if o_r['pnl'] > 0 and i_r['pnl'] > 0:
            verdict = "✅ REAL"
        elif o_r['pnl'] > 0 and i_r['pnl'] <= 0:
            verdict = "🔄 MEJORA"
        elif o_r['pnl'] <= 0 and i_r['pnl'] > 0:
            verdict = "❌ OVERFIT"
        elif o_r['n'] == 0:
            verdict = "🤫 SILENCIO"
        else:
            verdict = "💀 MUERTA"
        
        # Robustness: does the strategy maintain WR and PF?
        wr_stable = abs(o_r['wr'] - i_r['wr']) < 20 if i_r['n'] > 0 and o_r['n'] > 0 else True
        
        print(f"   {i_r['name']:<28} ${i_r['pnl']:>+7.2f} ${o_r['pnl']:>+8.2f} ${delta:>+7.2f}   {verdict}")
    
    # ═══ DETAILED TOP OOS ═══
    ranked_oos = sorted(out_results, key=lambda x: x['pnl'], reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i+4}." for i in range(5)]
    print(f"\n{'=' * 80}")
    print(f"🏆 RANKING OUT-OF-SAMPLE (lo que REALMENTE importa)")
    print(f"{'=' * 80}")
    for i, r in enumerate(ranked_oos):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        bar = "█" * max(1, int(max(0, r['pnl']) / 8))
        neg = "▓" * max(0, int(abs(min(0, r['pnl'])) / 8))
        print(f"  {medals[i]} {e} {r['name']:<28} ${r['pnl']:>+8.2f}  {bar}{neg}")
    
    # ═══ FINAL VERDICT ═══
    print(f"\n{'=' * 80}")
    print(f"💡 VEREDICTO FINAL")
    print(f"{'=' * 80}")
    
    # Find strategies that are REAL (positive in both)
    real = []
    overfit = []
    for i_r, o_r in zip(in_results, out_results):
        if i_r['pnl'] > 0 and o_r['pnl'] > 0:
            real.append((i_r['name'], i_r['pnl'], o_r['pnl']))
        elif i_r['pnl'] > 0 and o_r['pnl'] <= 0:
            overfit.append((i_r['name'], i_r['pnl'], o_r['pnl']))
    
    if real:
        print(f"\n  ✅ ESTRATEGIAS REALES (ganan en datos conocidos Y desconocidos):")
        for name, in_pnl, out_pnl in real:
            consistency = min(in_pnl, out_pnl) / max(in_pnl, out_pnl) * 100
            print(f"     {name}: In ${in_pnl:+.2f} → Out ${out_pnl:+.2f} | Consistencia: {consistency:.0f}%")
    
    if overfit:
        print(f"\n  ❌ OVERFITTING (ganaban con datos conocidos, PIERDEN en ciego):")
        for name, in_pnl, out_pnl in overfit:
            print(f"     {name}: In ${in_pnl:+.2f} → Out ${out_pnl:+.2f} ← Falsa confianza")
    
    # Best OOS
    best_oos = ranked_oos[0]
    print(f"\n  🏆 Mejor en test ciego: {best_oos['name']}")
    print(f"     PnL: ${best_oos['pnl']:+.2f} | {best_oos['n']} trades | WR: {best_oos['wr']:.0f}% | DD: {best_oos['dd']:.1f}%")

if __name__ == "__main__":
    asyncio.run(main())
