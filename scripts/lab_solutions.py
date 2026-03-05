"""
CT4 Lab — Solutions Testing
=============================
Compara: Original vs Momentum Adaptativa vs 5 mejoras propuestas
usando datos reales. Incluye SL/TP dinámico y tracking detallado.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

TIMEFRAME = "5m"
CAPITAL = 10000

def calc(df):
    df['EMA9'] = df['close'].ewm(span=9).mean()
    df['EMA21'] = df['close'].ewm(span=21).mean()
    df['EMA200'] = df['close'].ewm(span=200).mean()
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, abs(h-c.shift(1)), abs(l-c.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    pdm = h.diff().where(lambda x: (x > 0) & (x > -l.diff()), 0)
    mdm = (-l.diff()).where(lambda x: (x > 0) & (x > h.diff()), 0)
    pdi = 100 * (pdm.rolling(14).mean() / df['ATR'])
    mdi = 100 * (mdm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(pdi - mdi) / (pdi + mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['VSMA'] = df['volume'].rolling(20).mean()
    df['BB_MID'] = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df['BB_LO'] = df['BB_MID'] - 2 * bb_std
    df['BB_HI'] = df['BB_MID'] + 2 * bb_std
    df['BB_PCT'] = (c - df['BB_LO']) / (df['BB_HI'] - df['BB_LO'] + 1e-10)
    return df

def g(row, col, default=0):
    v = row.get(col, default)
    return default if pd.isna(v) else v

def backtest(df, name, buy_fn, exit_fn, sl_fn, tp_fn, trailing=False):
    cap = CAPITAL
    peak = CAPITAL
    max_dd = 0
    pos = None
    trades = []
    
    for i in range(202, len(df)-1):
        r = df.iloc[i]
        p1 = df.iloc[i-1]
        p2 = df.iloc[i-2]
        
        if pos is None:
            if buy_fn(r, p1, p2):
                atr = g(r, 'ATR', 100)
                sl = sl_fn(r['close'], atr, g(r, 'ADX', 30))
                tp = tp_fn(r['close'], atr, g(r, 'ADX', 30))
                sz = (cap * 0.3) / r['close']
                pos = {'entry': r['close'], 'sl': sl, 'tp': tp, 'sz': sz, 'bar': i, 'peak': r['close']}
        else:
            price = r['close']
            pos['peak'] = max(pos['peak'], price)
            
            # Trailing SL
            if trailing and price > pos['entry'] * 1.005:
                new_sl = max(pos['sl'], price - 1.0 * g(r, 'ATR', 100))
                pos['sl'] = new_sl
            
            pnl = None
            etype = None
            if price <= pos['sl']:
                pnl = (pos['sl'] - pos['entry']) * pos['sz']
                etype = 'SL'
            elif price >= pos['tp']:
                pnl = (pos['tp'] - pos['entry']) * pos['sz']
                etype = 'TP'
            elif exit_fn(r, p1):
                pnl = (price - pos['entry']) * pos['sz']
                etype = 'EXIT'
            
            if pnl is not None:
                cap += pnl
                peak = max(peak, cap)
                dd = (peak - cap) / peak * 100
                max_dd = max(max_dd, dd)
                trades.append({'pnl': pnl, 'pct': (pnl/(pos['entry']*pos['sz']))*100, 'type': etype, 'bars': i-pos['bar'], 'entry': pos['entry'], 'exit': price})
                pos = None
    
    if pos:
        pnl = (df.iloc[-1]['close'] - pos['entry']) * pos['sz']
        cap += pnl
        trades.append({'pnl': pnl, 'pct': (pnl/(pos['entry']*pos['sz']))*100, 'type': 'OPEN', 'bars': 0, 'entry': pos['entry'], 'exit': df.iloc[-1]['close']})
    
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] <= 0]
    return {
        'name': name, 'trades': len(trades), 'wins': len(w), 'losses': len(l),
        'wr': len(w)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades),
        'ret': ((cap-CAPITAL)/CAPITAL)*100,
        'dd': max_dd,
        'pf': sum(t['pnl'] for t in w) / abs(sum(t['pnl'] for t in l)) if l and sum(t['pnl'] for t in l) != 0 else 999,
        'avg_bars': np.mean([t['bars'] for t in trades]) if trades else 0,
        'details': trades, 'cap': cap
    }

# ═══ EXIT (shared) ═══
def exit_base(r, p):
    cd = g(p,'EMA9') >= g(p,'EMA21') and g(r,'EMA9') < g(r,'EMA21')
    lm = r['close'] < g(r,'EMA200') * 0.985
    return cd or lm

# ═══ SL/TP FUNCTIONS ═══
def sl_fixed(price, atr, adx): return price - 1.5 * atr
def tp_fixed(price, atr, adx): return price + 3.0 * atr

def sl_adaptive(price, atr, adx):
    mult = 2.5 if adx > 50 else 2.0 if adx > 35 else 1.5
    return price - mult * atr

def tp_adaptive(price, atr, adx):
    mult = 4.0 if adx > 50 else 3.5 if adx > 35 else 3.0
    return price + mult * atr

def sl_tight(price, atr, adx): return price - 1.0 * atr
def tp_wide(price, atr, adx): return price + 4.0 * atr

# ═══ STRATEGIES ═══

def buy_original(r, p1, p2):
    """A. Original estricto: 4 leyes"""
    marea = r['close'] > g(r,'EMA200')
    fuerza = g(r,'ADX') > 20
    ballenas = r['volume'] > g(r,'VSMA') if g(r,'VSMA') > 0 else False
    pb = g(p1,'RSI') < 35 and g(r,'RSI') > g(p1,'RSI')
    return marea and fuerza and ballenas and pb

def buy_momentum(r, p1, p2):
    """B. Momentum Adaptativa: 4 leyes flex + 2 velas"""
    atr = g(r,'ATR',100)
    atr_pct = (atr/r['close'])*100
    hv = atr_pct > 0.5
    rsi, prsi, p2rsi = g(r,'RSI',50), g(p1,'RSI',50), g(p2,'RSI',50)
    adx = g(r,'ADX')
    # Override
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']:
        return True
    rt = 40 if hv else 35
    at = 15 if hv else 20
    mt = 0.02 if hv else 0.01
    marea = r['close'] > g(r,'EMA200') * (1 - mt)
    fuerza = adx > at
    ballenas = r['volume'] > g(r,'VSMA') * 0.8 if g(r,'VSMA') > 0 else False
    pb = prsi < rt and rsi > prsi and prsi > p2rsi
    return marea and fuerza and ballenas and pb

def buy_sol1_sl_adapt(r, p1, p2):
    """C. Original + SL Adaptativo (solución #1)"""
    return buy_original(r, p1, p2)

def buy_sol2_momentum_confirm(r, p1, p2):
    """D. Original + Confirmación 2 velas (solución #2)"""
    if not buy_original(r, p1, p2): return False
    return g(r,'RSI') > g(p1,'RSI') and g(p1,'RSI') > g(p2,'RSI')

def buy_sol3_adx_cap(r, p1, p2):
    """E. Original + ADX Cap (no comprar si ADX > 70)"""
    marea = r['close'] > g(r,'EMA200')
    adx = g(r,'ADX')
    fuerza = 20 < adx < 70  # Cap at 70!
    ballenas = r['volume'] > g(r,'VSMA') if g(r,'VSMA') > 0 else False
    pb = g(p1,'RSI') < 35 and g(r,'RSI') > g(p1,'RSI')
    return marea and fuerza and ballenas and pb

def buy_sol4_trailing(r, p1, p2):
    """F. Original + Trailing Stop"""
    return buy_original(r, p1, p2)

def buy_sol5_combined(r, p1, p2):
    """G. COMBINADA: SL Adapt + 2 velas + ADX cap"""
    marea = r['close'] > g(r,'EMA200')
    adx = g(r,'ADX')
    fuerza = 20 < adx < 70
    ballenas = r['volume'] > g(r,'VSMA') if g(r,'VSMA') > 0 else False
    rsi, prsi, p2rsi = g(r,'RSI',50), g(p1,'RSI',50), g(p2,'RSI',50)
    pb = prsi < 35 and rsi > prsi and prsi > p2rsi
    return marea and fuerza and ballenas and pb

def buy_ultimate(r, p1, p2):
    """H. ULTIMATE: Combinada + Override RSI + Bollinger"""
    rsi, prsi, p2rsi = g(r,'RSI',50), g(p1,'RSI',50), g(p2,'RSI',50)
    adx = g(r,'ADX')
    # Override RSI extremo
    if prsi < 20 and rsi > prsi and adx > 35 and r['close'] > r['open']:
        return True
    # Combinada estricta
    marea = r['close'] > g(r,'EMA200')
    fuerza = 20 < adx < 70
    ballenas = r['volume'] > g(r,'VSMA') * 0.8 if g(r,'VSMA') > 0 else False
    pb = prsi < 38 and rsi > prsi and prsi > p2rsi
    bb = g(r, 'BB_PCT', 0.5) < 0.35
    return marea and fuerza and ballenas and pb and bb

async def main():
    print("=" * 70)
    print("🔬 CT4 LAB — Test de Soluciones vs Original vs Momentum")
    print("=" * 70)
    
    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv('BTC/USDT', TIMEFRAME, limit=1000)
    await exchange.close()
    
    df = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)
    
    print(f"\n✅ {len(df)} velas | {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")
    print(f"   Rango: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    
    configs = [
        ("A. ORIGINAL (actual)",           buy_original,          exit_base, sl_fixed,    tp_fixed,    False),
        ("B. MOMENTUM ADAPTATIVA",         buy_momentum,          exit_base, sl_fixed,    tp_fixed,    False),
        ("C. Original + SL Adaptativo",    buy_sol1_sl_adapt,     exit_base, sl_adaptive, tp_adaptive, False),
        ("D. Original + 2 velas confirm",  buy_sol2_momentum_confirm, exit_base, sl_fixed, tp_fixed,  False),
        ("E. Original + ADX Cap (<70)",    buy_sol3_adx_cap,      exit_base, sl_fixed,    tp_fixed,    False),
        ("F. Original + Trailing Stop",    buy_sol4_trailing,     exit_base, sl_fixed,    tp_fixed,    True),
        ("G. COMBINADA (SL+2vel+ADXcap)",  buy_sol5_combined,     exit_base, sl_adaptive, tp_adaptive, False),
        ("H. ULTIMATE (combo+override+BB)",buy_ultimate,          exit_base, sl_adaptive, tp_adaptive, True),
        ("I. Original + SL tight TP wide", buy_original,          exit_base, sl_tight,    tp_wide,     False),
        ("J. Momentum + SL Adaptativo",    buy_momentum,          exit_base, sl_adaptive, tp_adaptive, False),
    ]
    
    results = []
    for name, buy, exit_fn, sl, tp, trail in configs:
        r = backtest(df, name, buy, exit_fn, sl, tp, trail)
        results.append(r)
    
    # Print all results
    print(f"\n{'='*70}")
    print(f"📊 RESULTADOS — {len(df)} velas ({len(df)*5/60:.0f}h)")
    print(f"{'='*70}")
    print(f"\n   {'Estrategia':<42} {'T':>3} {'W':>3} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   " + "-" * 75)
    
    for r in results:
        e = "🟢" if r['pnl'] > 0 else ("🔴" if r['pnl'] < 0 else "⚪")
        print(f"   {e} {r['name']:<40} {r['trades']:>3} {r['wins']:>3} {r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {r['pf']:>5.1f}")
    
    # Top 3 details
    ranked = sorted(results, key=lambda x: x['pnl'], reverse=True)
    
    print(f"\n{'='*70}")
    print("🏆 RANKING FINAL")
    print(f"{'='*70}")
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, r in enumerate(ranked):
        e = "🟢" if r['pnl'] > 0 else "🔴"
        print(f"  {medals[i]} {e} {r['name']:<42} {r['trades']:>2}T {r['wr']:>4.0f}% ${r['pnl']:>+8.2f} DD:{r['dd']:.1f}%")
    
    # Winner details
    w = ranked[0]
    print(f"\n{'='*70}")
    print(f"⭐ GANADORA: {w['name']}")
    print(f"   Trades: {w['trades']} | Wins: {w['wins']} | Win Rate: {w['wr']:.0f}%")
    print(f"   PnL: ${w['pnl']:+.2f} ({w['ret']:+.2f}%) | Max DD: {w['dd']:.2f}% | PF: {w['pf']:.2f}")
    print(f"   Capital: $10,000 → ${w['cap']:.2f}")
    for t in w['details']:
        e = "🟢" if t['pnl'] > 0 else "🔴"
        print(f"   {e} ${t['entry']:.0f}→${t['exit']:.0f} | {t['type']:>4} | ${t['pnl']:+.2f} ({t['pct']:+.1f}%) | {t['bars']*5}min")
    
    # vs Original comparison
    orig = results[0]
    print(f"\n{'='*70}")
    print(f"📊 COMPARACIÓN vs ORIGINAL")
    print(f"{'='*70}")
    print(f"   {'Métrica':<20} {'Original':>12} {'Ganadora':>12} {'Mejora':>10}")
    print(f"   {'-'*56}")
    print(f"   {'PnL':<20} ${orig['pnl']:>+10.2f} ${w['pnl']:>+10.2f} {'×'+str(round(w['pnl']/orig['pnl'],1)) if orig['pnl'] != 0 else 'N/A':>10}")
    print(f"   {'Win Rate':<20} {orig['wr']:>10.0f}% {w['wr']:>10.0f}% {w['wr']-orig['wr']:>+9.0f}%")
    print(f"   {'Max Drawdown':<20} {orig['dd']:>10.1f}% {w['dd']:>10.1f}% {w['dd']-orig['dd']:>+9.1f}%")
    print(f"   {'Profit Factor':<20} {orig['pf']:>10.1f} {w['pf']:>10.1f} {'×'+str(round(w['pf']/orig['pf'],1)) if orig['pf'] not in [0,999] else 'N/A':>10}")

if __name__ == "__main__":
    asyncio.run(main())
