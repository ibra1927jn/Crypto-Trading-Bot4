"""
CT4 LAB — TEST CIEGO EXTREMO (2+ Semanas)
============================================
Descarga la MÁXIMA cantidad de datos disponibles en Binance Testnet.
Busca subidas, crashes, y caos real.

Split: 
  Los primeros 70% = IN-SAMPLE (entrenamiento)
  Los últimos 30% = OUT-OF-SAMPLE (ciego total)
  
Las estrategias NO saben qué viene. Todo es walk-forward.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

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
    equity_curve = []
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
        equity_curve.append(cap)
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['e']) * pos['sz']; cap += pnl
        trades.append({'pnl': pnl, 't': 'OPEN', 'e': pos['e'],
                       'x': df.iloc[-1]['close'], 'bars': 0,
                       'pct': (pnl / (pos['e'] * pos['sz'])) * 100})
    w = [t for t in trades if t['pnl'] > 0]
    lo = [t for t in trades if t['pnl'] <= 0]
    gl = sum(t['pnl'] for t in lo) if lo else 0
    # Consecutive losses
    max_consec_loss = 0; curr = 0
    for t in trades:
        if t['pnl'] <= 0: curr += 1; max_consec_loss = max(max_consec_loss, curr)
        else: curr = 0
    return {
        'name': name, 'n': len(trades), 'w': len(w), 'l': len(lo),
        'wr': len(w) / len(trades) * 100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades), 'dd': dd, 'cap': cap,
        'pf': sum(t['pnl'] for t in w) / abs(gl) if gl != 0 else 999,
        'avg_hold': np.mean([t['bars'] * 5 for t in trades]) if trades else 0,
        'max_win': max([t['pnl'] for t in w]) if w else 0,
        'max_loss': min([t['pnl'] for t in lo]) if lo else 0,
        'max_consec_loss': max_consec_loss,
        'details': trades, 'equity': equity_curve
    }

# ═══ EXITS ═══
def exit_ema(r, p):
    return ((v(p, 'EMA9') >= v(p, 'EMA21') and v(r, 'EMA9') < v(r, 'EMA21'))
            or r['close'] < v(r, 'EMA200') * 0.985)
def exit_bb(r, p):
    return v(r, 'BB_PCT') > 0.95 or exit_ema(r, p)
def exit_never(r, p):
    return False

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

def detect_phases(df):
    """Detecta fases del mercado: rally, crash, lateral."""
    phases = []
    window = 48  # 4 horas por fase
    for i in range(0, len(df) - window, window):
        chunk = df.iloc[i:i+window]
        ret = (chunk.iloc[-1]['close'] - chunk.iloc[0]['close']) / chunk.iloc[0]['close'] * 100
        adx_avg = chunk['ADX'].mean()
        vol = chunk['volume'].mean()
        vol_sma = chunk['VSMA'].mean() if 'VSMA' in chunk.columns else vol
        ts = chunk.index[0].strftime('%m/%d %H:%M')
        if ret > 1.5:
            phases.append(('🟢 RALLY', ts, ret, adx_avg))
        elif ret < -1.5:
            phases.append(('🔴 CRASH', ts, ret, adx_avg))
        else:
            phases.append(('⚪ LATERAL', ts, ret, adx_avg))
    return phases

async def main():
    print("=" * 80)
    print("💀 CT4 LAB — TEST CIEGO EXTREMO (2+ Semanas de Caos)")
    print("=" * 80)

    exchange = ccxt.binance({'sandbox': True})

    # Go back as far as possible: try Feb 10
    # 2 weeks = 14 days × 288 candles/day = 4032 candles
    # We'll try going back further for EMA200 warmup
    start_dates = [
        datetime(2026, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 15, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 20, 0, 0, tzinfo=timezone.utc),
    ]
    
    all_candles = []
    
    for start_dt in start_dates:
        since = int(start_dt.timestamp() * 1000)
        end_ts = int(datetime(2026, 3, 5, 5, 0, tzinfo=timezone.utc).timestamp() * 1000)
        
        batch_count = 0
        while since < end_ts and batch_count < 10:
            try:
                candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=1000)
                if not candles:
                    break
                all_candles.extend(candles)
                since = candles[-1][0] + 1
                batch_count += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"  ⚠️ Error at batch {batch_count}: {e}")
                break
        
        if all_candles:
            print(f"  📥 Desde {start_dt.strftime('%m/%d')}: {len(all_candles)} velas cargadas")
            break  # If first date works, use it
        else:
            print(f"  ⚠️ No data from {start_dt.strftime('%m/%d')}, trying later...")
    
    await exchange.close()

    # Deduplicate
    seen = set(); unique = []
    for c in all_candles:
        if c[0] not in seen: seen.add(c[0]); unique.append(c)
    unique.sort(key=lambda x: x[0])

    df = pd.DataFrame(unique, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)
    
    total_hrs = len(df) * 5 / 60
    total_days = total_hrs / 24

    # ═══ MARKET ANATOMY ═══
    print(f"\n{'=' * 80}")
    print(f"📊 ANATOMÍA DEL MERCADO")
    print(f"{'=' * 80}")
    print(f"  Velas:     {len(df)} ({total_hrs:.0f}h = {total_days:.1f} días)")
    print(f"  Período:   {df.index[0].strftime('%Y-%m-%d %H:%M')} → {df.index[-1].strftime('%Y-%m-%d %H:%M')}")
    print(f"  Rango:     ${df['close'].min():.0f} — ${df['close'].max():.0f} (${df['close'].max()-df['close'].min():.0f})")
    print(f"  ADX Max:   {df['ADX'].max():.0f}")
    print(f"  ADX Min:   {df['ADX'].min():.0f}")
    print(f"  RSI Max:   {df['RSI'].max():.0f}")
    print(f"  RSI Min:   {df['RSI'].min():.0f}")
    print(f"  ATR avg:   ${df['ATR'].mean():.0f}")
    
    # Market phases
    phases = detect_phases(df)
    rallies = [p for p in phases if 'RALLY' in p[0]]
    crashes = [p for p in phases if 'CRASH' in p[0]]
    laterals = [p for p in phases if 'LATERAL' in p[0]]
    print(f"\n  Fases detectadas:")
    print(f"    🟢 Rallies:  {len(rallies)} ({len(rallies)*4}h)")
    print(f"    🔴 Crashes:  {len(crashes)} ({len(crashes)*4}h)")
    print(f"    ⚪ Lateral:  {len(laterals)} ({len(laterals)*4}h)")
    
    # Show extreme events
    print(f"\n  Eventos extremos:")
    for p in phases:
        if abs(p[2]) > 3:
            print(f"    {p[0]} {p[1]} | {p[2]:+.1f}% | ADX {p[3]:.0f}")

    # ═══ SPLIT: 70/30 ═══
    cut_pct = 0.70
    cut_idx = int(len(df) * cut_pct)
    
    # Make sure we leave enough warmup for OOS
    df_in = df.iloc[:cut_idx].copy()
    df_out_full = df.copy()  # Full data for OOS (recalc indicators)
    # For OOS: use data from cut_idx-250 onwards so indicators have warmup
    oos_start = max(0, cut_idx - 250)
    df_out = df.iloc[oos_start:].copy()
    df_out = calc(df_out)  # Recalculate indicators for this slice
    
    in_hrs = len(df_in) * 5 / 60
    out_candles = len(df) - cut_idx
    out_hrs = out_candles * 5 / 60
    
    bh_in = (df_in.iloc[-1]['close'] - df_in.iloc[202]['close']) / df_in.iloc[202]['close'] * 100
    bh_out_start = df.iloc[cut_idx]['close']
    bh_out_end = df.iloc[-1]['close']
    bh_out = (bh_out_end - bh_out_start) / bh_out_start * 100
    
    print(f"\n{'=' * 80}")
    print(f"✂️  SPLIT WALK-FORWARD (70/30)")
    print(f"{'=' * 80}")
    print(f"  IN-SAMPLE:      {df_in.index[0].strftime('%m/%d')} → {df_in.index[-1].strftime('%m/%d')} | {len(df_in)} velas ({in_hrs:.0f}h = {in_hrs/24:.1f}d)")
    print(f"  OUT-OF-SAMPLE:  {df.index[cut_idx].strftime('%m/%d')} → {df.index[-1].strftime('%m/%d')} | {out_candles} velas ({out_hrs:.0f}h = {out_hrs/24:.1f}d)")
    print(f"  B&H In-Sample:  {bh_in:+.1f}%")
    print(f"  B&H Out-Sample: {bh_out:+.1f}%")

    # ═══ STRATEGIES ═══
    configs = [
        ("A. ORIGINAL V1",         buy_original,   exit_ema,   1.5, 3.0, False, False),
        ("B. MOMENTUM V2",         buy_momentum,   exit_ema,   1.5, 3.0, False, False),
        ("C. V2.1 PRODUCCIÓN ★",   buy_v21,        exit_ema,   1.5, 3.0, True,  False),
        ("D. BOLLINGER BOUNCE",    buy_bollinger,   exit_bb,    1.5, 3.0, True,  False),
        ("E. BB SQUEEZE",          buy_squeeze,     exit_never, 1.5, 3.0, False, False),
        ("F. STOCHASTIC RSI",      buy_stoch_rsi,   exit_ema,   1.5, 3.0, True,  False),
        ("G. ULTIMATE V2",         buy_ultimate,    exit_ema,   1.5, 3.0, True,  True),
    ]

    in_results = []
    out_results = []
    for name, buy, exit_fn, sl, tp, trail, adapt in configs:
        r_in = backtest(df_in, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt)
        r_out = backtest(df_out, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt)
        in_results.append(r_in)
        out_results.append(r_out)

    # ═══ IN-SAMPLE ═══
    print(f"\n{'=' * 80}")
    print(f"📊 IN-SAMPLE (datos conocidos)")
    print(f"{'=' * 80}")
    hdr = f"   {'Estrategia':<26} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5} {'MaxCL':>5}"
    print(hdr)
    print("   " + "-" * 70)
    for r in in_results:
        e = "🟢" if r['pnl'] > 0 else "🔴"
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<24} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {pf:>5} {r['max_consec_loss']:>4}")

    # ═══ OUT-OF-SAMPLE ═══
    print(f"\n{'=' * 80}")
    print(f"🔮 OUT-OF-SAMPLE (TEST CIEGO — datos NUNCA vistos)")
    print(f"{'=' * 80}")
    print(hdr)
    print("   " + "-" * 70)
    for r in out_results:
        e = "🟢" if r['pnl'] > 0 else "🔴"
        pf = f"{r['pf']:.1f}" if r['pf'] < 100 else "∞"
        print(f"   {e} {r['name']:<24} {r['n']:>3} {r['w']:>2} {r['l']:>2} "
              f"{r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {pf:>5} {r['max_consec_loss']:>4}")

    # ═══ WALK-FORWARD ═══
    print(f"\n{'=' * 80}")
    print(f"⚖️  WALK-FORWARD: Honestidad Brutal")
    print(f"{'=' * 80}")
    print(f"   {'Estrategia':<26} {'In-Sample':>10} {'Out-Sample':>10} {'Δ%':>8} {'Verdict':>12}")
    print("   " + "-" * 72)
    for i_r, o_r in zip(in_results, out_results):
        if i_r['pnl'] != 0:
            delta_pct = ((o_r['pnl'] - i_r['pnl']) / abs(i_r['pnl'])) * 100
        else:
            delta_pct = 999
        if o_r['pnl'] > 0 and i_r['pnl'] > 0: verdict = "✅ REAL"
        elif o_r['pnl'] > 0 and i_r['pnl'] <= 0: verdict = "🔄 MEJORA"
        elif o_r['pnl'] <= 0 and i_r['pnl'] > 0: verdict = "❌ OVERFIT"
        elif o_r['n'] == 0: verdict = "🤫 SILENCIO"
        else: verdict = "💀 MUERTA"
        print(f"   {i_r['name']:<26} ${i_r['pnl']:>+7.2f} ${o_r['pnl']:>+8.2f} {delta_pct:>+6.0f}%   {verdict}")

    # ═══ RANKING OOS ═══
    ranked = sorted(out_results, key=lambda x: x['pnl'], reverse=True)
    medals = ["🥇", "🥈", "🥉"] + [f"{i+4}." for i in range(4)]
    print(f"\n{'=' * 80}")
    print(f"🏆 RANKING OUT-OF-SAMPLE (la VERDAD)")
    print(f"{'=' * 80}")
    for i, r in enumerate(ranked):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        bar = "█" * max(1, int(max(0, r['pnl']) / 8))
        neg = "▓" * max(0, int(abs(min(0, r['pnl'])) / 8))
        print(f"  {medals[i]} {e} {r['name']:<26} ${r['pnl']:>+8.2f} | WR {r['wr']:>4.0f}% | "
              f"PF {r['pf']:>4.1f} | DD {r['dd']:>3.1f}%  {bar}{neg}")

    # ═══ RISK ANALYSIS ═══
    print(f"\n{'=' * 80}")
    print(f"🛡️ ANÁLISIS DE RIESGO (Out-of-Sample)")
    print(f"{'=' * 80}")
    print(f"   {'Estrategia':<26} {'MaxWin':>8} {'MaxLoss':>8} {'MaxCL':>4} {'DD%':>5} {'PnL/DD':>7}")
    print("   " + "-" * 60)
    for r in ranked:
        pnl_dd = r['pnl'] / r['dd'] if r['dd'] > 0 else 999
        print(f"   {r['name']:<26} ${r['max_win']:>+6.0f} ${r['max_loss']:>+6.0f} "
              f"{r['max_consec_loss']:>4} {r['dd']:>4.1f}% {pnl_dd:>+6.0f}")

    # ═══ FINAL VERDICT ═══
    print(f"\n{'=' * 80}")
    print(f"💡 VEREDICTO FINAL — {total_days:.0f} DÍAS DE DATOS")
    print(f"{'=' * 80}")
    real = [(i_r['name'], i_r['pnl'], o_r['pnl'], o_r['wr'], o_r['dd'], o_r['pf'])
            for i_r, o_r in zip(in_results, out_results)
            if i_r['pnl'] > 0 and o_r['pnl'] > 0]
    overfit = [(i_r['name'], i_r['pnl'], o_r['pnl'])
               for i_r, o_r in zip(in_results, out_results)
               if i_r['pnl'] > 0 and o_r['pnl'] <= 0]
    
    if real:
        print(f"\n  ✅ ESTRATEGIAS REALES ({len(real)}/{len(configs)}):")
        for name, ip, op, wr, dd, pf in sorted(real, key=lambda x: -x[2]):
            cons = min(ip, op) / max(ip, op) * 100
            print(f"     {name}: In ${ip:+.0f} → Out ${op:+.0f} | "
                  f"WR {wr:.0f}% | DD {dd:.1f}% | PF {pf:.1f} | Cons {cons:.0f}%")
    if overfit:
        print(f"\n  ❌ OVERFITTING ({len(overfit)}):")
        for name, ip, op in overfit:
            print(f"     {name}: In ${ip:+.0f} → Out ${op:+.0f}")

    best = ranked[0]
    print(f"\n  🏆 CAMPEÓN CIEGO: {best['name']}")
    print(f"     ${best['pnl']:+.2f} | {best['n']} trades | WR {best['wr']:.0f}% | DD {best['dd']:.1f}% | PF {best['pf']:.1f}")
    print(f"     Max Pérdidas Consecutivas: {best['max_consec_loss']}")

if __name__ == "__main__":
    asyncio.run(main())
