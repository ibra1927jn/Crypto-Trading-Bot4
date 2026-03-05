"""
CT4 Lab — Advanced Experiments
================================
Tests que VAN MÁS ALLÁ del backtest simple:

1. WALK-FORWARD: Entrena en 70% datos, prueba en 30% (anti-trampa)
2. STRESS TEST: ¿Qué pasa en caídas fuertes? ¿Y en subidas?
3. MULTI-TIMEFRAME: ¿5min, 15min o 1h es mejor?
4. POSITION SIZING: ¿10%, 20%, 30% o 50% del capital?
5. MONTE CARLO: 100 simulaciones randomizadas
"""
import asyncio, sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

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
    pdi = 100*(pdm.rolling(14).mean()/df['ATR'])
    mdi = 100*(mdm.rolling(14).mean()/df['ATR'])
    dx = 100*abs(pdi-mdi)/(pdi+mdi)
    df['ADX'] = dx.rolling(14).mean()
    df['VSMA'] = df['volume'].rolling(20).mean()
    df['BB_MID'] = c.rolling(20).mean()
    bs = c.rolling(20).std()
    df['BB_LO'] = df['BB_MID'] - 2*bs
    df['BB_HI'] = df['BB_MID'] + 2*bs
    df['BB_PCT'] = (c - df['BB_LO'])/(df['BB_HI']-df['BB_LO']+1e-10)
    return df

def g(r, c, d=0):
    v = r.get(c, d); return d if pd.isna(v) else v

def run(df, buy_fn, risk=0.3, sl_m=1.5, tp_m=3.0, adapt_sl=False):
    cap = 10000; peak = 10000; dd = 0; pos = None; trades = []
    for i in range(202, len(df)-1):
        r, p1, p2 = df.iloc[i], df.iloc[i-1], df.iloc[i-2]
        if pos is None:
            if buy_fn(r, p1, p2):
                atr = g(r,'ATR',100)
                adx = g(r,'ADX',30)
                sm = (2.5 if adx>50 else 2.0 if adx>35 else 1.5) if adapt_sl else sl_m
                tm = (4.0 if adx>50 else 3.5 if adx>35 else 3.0) if adapt_sl else tp_m
                sz = (cap*risk)/r['close']
                pos = {'e': r['close'], 'sl': r['close']-sm*atr, 'tp': r['close']+tm*atr, 'sz': sz, 'b': i}
        else:
            p = r['close']
            pnl = None
            if p <= pos['sl']: pnl = (pos['sl']-pos['e'])*pos['sz']; t='SL'
            elif p >= pos['tp']: pnl = (pos['tp']-pos['e'])*pos['sz']; t='TP'
            elif g(p1,'EMA9')>=g(p1,'EMA21') and g(r,'EMA9')<g(r,'EMA21'):
                pnl = (p-pos['e'])*pos['sz']; t='EXIT'
            if pnl is not None:
                cap += pnl; peak = max(peak,cap); dd = max(dd,(peak-cap)/peak*100)
                trades.append({'pnl':pnl,'t':t}); pos = None
    if pos:
        pnl=(df.iloc[-1]['close']-pos['e'])*pos['sz']; cap+=pnl
        trades.append({'pnl':pnl,'t':'OPEN'})
    w=[t for t in trades if t['pnl']>0]
    return {'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
            'pnl':sum(t['pnl'] for t in trades),'dd':dd,'cap':cap}

# ═══ STRATEGIES ═══
def original(r, p1, p2):
    return (r['close']>g(r,'EMA200') and g(r,'ADX')>20 and
            r['volume']>g(r,'VSMA') and g(p1,'RSI')<35 and g(r,'RSI')>g(p1,'RSI'))

def momentum(r, p1, p2):
    rsi,prsi,p2rsi = g(r,'RSI',50),g(p1,'RSI',50),g(p2,'RSI',50)
    adx = g(r,'ADX')
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']: return True
    atr_pct=(g(r,'ATR',100)/r['close'])*100; hv=atr_pct>0.5
    rt=40 if hv else 35; at=15 if hv else 20; mt=0.02 if hv else 0.01
    return (r['close']>g(r,'EMA200')*(1-mt) and adx>at and
            r['volume']>g(r,'VSMA')*0.8 and prsi<rt and rsi>prsi and prsi>p2rsi)

def momentum_sl(r, p1, p2): return momentum(r, p1, p2)

async def main():
    print("="*70)
    print("🧪 CT4 LAB — Experimentos Avanzados")
    print("="*70)
    
    exchange = ccxt.binance({'sandbox': True})
    
    # Download multiple timeframes
    print("\n📥 Descargando datos multi-timeframe...")
    dfs = {}
    for tf in ['5m', '15m', '1h']:
        c = await exchange.fetch_ohlcv('BTC/USDT', tf, limit=1000)
        d = pd.DataFrame(c, columns=['timestamp','open','high','low','close','volume'])
        d['timestamp'] = pd.to_datetime(d['timestamp'], unit='ms')
        d.set_index('timestamp', inplace=True)
        dfs[tf] = calc(d)
        hrs = len(d) * {'5m':5,'15m':15,'1h':60}[tf] / 60
        print(f"   ✅ {tf}: {len(d)} velas ({hrs:.0f}h) | ${d['close'].min():.0f}-${d['close'].max():.0f}")
    
    await exchange.close()
    df = dfs['5m']
    
    # ═══════════════════════════════════════════════════════════
    # TEST 1: WALK-FORWARD (anti-trampa)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("🛡️ TEST 1: WALK-FORWARD (70% entrenamiento / 30% prueba)")
    print("   → Si gana en la parte que NO vio, es REAL")
    print(f"{'='*70}")
    
    split = int(len(df) * 0.7)
    train = df.iloc[:split].copy()
    test = df.iloc[split:].copy()
    
    print(f"   Entrenamiento: {len(train)} velas ({train.index[0].strftime('%m/%d %H:%M')} → {train.index[-1].strftime('%m/%d %H:%M')})")
    print(f"   Prueba:        {len(test)} velas ({test.index[0].strftime('%m/%d %H:%M')} → {test.index[-1].strftime('%m/%d %H:%M')})")
    
    strats = [("Original", original, False), ("Momentum", momentum, False), ("Momentum+SL Adapt", momentum_sl, True)]
    
    print(f"\n   {'Estrategia':<25} {'--- ENTRENAMIENTO ---':>25} {'--- PRUEBA (NO VISTO) ---':>30}")
    print(f"   {'':25} {'T':>3} {'WR%':>5} {'PnL':>10}   {'T':>3} {'WR%':>5} {'PnL':>10}")
    print("   " + "-"*70)
    
    for name, fn, adapt in strats:
        r_train = run(train, fn, adapt_sl=adapt)
        r_test = run(test, fn, adapt_sl=adapt)
        et = "🟢" if r_train['pnl']>0 else "🔴"
        ep = "🟢" if r_test['pnl']>0 else "🔴"
        consistent = "✅" if (r_train['pnl']>0) == (r_test['pnl']>0) else "⚠️"
        print(f"   {consistent} {name:<23} {et} {r_train['n']:>3} {r_train['wr']:>4.0f}% ${r_train['pnl']:>+8.2f}   {ep} {r_test['n']:>3} {r_test['wr']:>4.0f}% ${r_test['pnl']:>+8.2f}")
    
    # ═══════════════════════════════════════════════════════════
    # TEST 2: STRESS TEST (diferentes condiciones de mercado)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("💥 TEST 2: STRESS TEST — Rendimiento por tipo de mercado")
    print(f"{'='*70}")
    
    # Split df into market phases
    phases = []
    chunk = 150
    for i in range(0, len(df)-chunk, chunk):
        sub = df.iloc[i:i+chunk]
        change = (sub.iloc[-1]['close'] - sub.iloc[0]['close']) / sub.iloc[0]['close'] * 100
        vol = sub['close'].std() / sub['close'].mean() * 100
        if change > 1: phase = "📈 ALCISTA"
        elif change < -1: phase = "📉 BAJISTA"
        else: phase = "↔️ LATERAL"
        phases.append((phase, change, vol, sub))
    
    print(f"\n   Fases detectadas en los datos:")
    for ph, ch, vol, sub in phases:
        print(f"   {ph} | Cambio: {ch:+.1f}% | Volatilidad: {vol:.2f}% | {sub.index[0].strftime('%m/%d %H:%M')}→{sub.index[-1].strftime('%m/%d %H:%M')}")
    
    print(f"\n   {'Estrategia':<22} {'📈 ALCISTA':>12} {'📉 BAJISTA':>12} {'↔️ LATERAL':>12}")
    print("   " + "-"*60)
    
    for name, fn, adapt in strats:
        pnls = {"📈 ALCISTA": 0, "📉 BAJISTA": 0, "↔️ LATERAL": 0}
        counts = {"📈 ALCISTA": 0, "📉 BAJISTA": 0, "↔️ LATERAL": 0}
        for ph, _, _, sub in phases:
            if len(sub) > 210:
                r = run(sub, fn, adapt_sl=adapt)
                pnls[ph] += r['pnl']
                counts[ph] += r['n']
        vals = []
        for ph in ["📈 ALCISTA", "📉 BAJISTA", "↔️ LATERAL"]:
            e = "🟢" if pnls[ph]>0 else ("🔴" if pnls[ph]<0 else "⚪")
            vals.append(f"{e}${pnls[ph]:>+6.0f}({counts[ph]}T)")
        print(f"   {name:<22} {vals[0]:>16} {vals[1]:>16} {vals[2]:>16}")
    
    # ═══════════════════════════════════════════════════════════
    # TEST 3: MULTI-TIMEFRAME
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("⏱️ TEST 3: MULTI-TIMEFRAME — ¿5min, 15min o 1h?")
    print(f"{'='*70}")
    
    print(f"\n   {'Estrategia':<22} {'5min':>14} {'15min':>14} {'1h':>14}")
    print("   " + "-"*65)
    
    for name, fn, adapt in strats:
        vals = []
        for tf in ['5m', '15m', '1h']:
            r = run(dfs[tf], fn, adapt_sl=adapt)
            e = "🟢" if r['pnl']>0 else "🔴"
            vals.append(f"{e}${r['pnl']:>+7.0f} {r['wr']:>2.0f}%({r['n']}T)")
        print(f"   {name:<22} {vals[0]:>18} {vals[1]:>18} {vals[2]:>18}")
    
    # ═══════════════════════════════════════════════════════════
    # TEST 4: POSITION SIZING
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("💰 TEST 4: POSITION SIZING — ¿Cuánto arriesgar por trade?")
    print(f"{'='*70}")
    
    print(f"\n   {'Estrategia':<22} {'10%':>12} {'20%':>12} {'30%':>12} {'50%':>12}")
    print("   " + "-"*72)
    
    for name, fn, adapt in strats:
        vals = []
        for risk in [0.10, 0.20, 0.30, 0.50]:
            r = run(df, fn, risk=risk, adapt_sl=adapt)
            e = "🟢" if r['pnl']>0 else "🔴"
            vals.append(f"{e}${r['pnl']:>+6.0f}")
        print(f"   {name:<22} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12} {vals[3]:>12}")
    
    # ═══════════════════════════════════════════════════════════
    # TEST 5: MONTE CARLO (100 simulaciones)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("🎲 TEST 5: MONTE CARLO — 100 simulaciones con datos barajados")
    print("   → Si gana en datos aleatorios, la estrategia tiene EDGE real")
    print(f"{'='*70}")
    
    for name, fn, adapt in strats:
        profits = []
        for _ in range(100):
            # Shuffle candles in blocks of 10 (mantener micro-estructura)
            blocks = [df.iloc[i:i+10] for i in range(0, len(df), 10)]
            random.shuffle(blocks)
            shuffled = pd.concat(blocks).reset_index(drop=True)
            shuffled = calc(shuffled)
            r = run(shuffled, fn, adapt_sl=adapt)
            profits.append(r['pnl'])
        
        wins = sum(1 for p in profits if p > 0)
        avg = np.mean(profits)
        med = np.median(profits)
        worst = min(profits)
        best = max(profits)
        e = "🟢" if avg > 0 else "🔴"
        print(f"   {e} {name:<22} | Gana {wins}/100 ({wins}%) | Avg: ${avg:+.1f} | Mediana: ${med:+.1f} | Peor: ${worst:+.1f} | Mejor: ${best:+.1f}")
    
    # ═══════════════════════════════════════════════════════════
    # RESUMEN FINAL
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("📋 RESUMEN FINAL — ¿Cuáles son las más robustas?")
    print(f"{'='*70}")
    print("""
   Criterio                  Original    Momentum    Mom+SL Adapt
   ──────────────────────────────────────────────────────────────
   Walk-Forward (anti-trampa)   ?           ?           ?
   Stress Test (mercados)       ?           ?           ?
   Multi-Timeframe              ?           ?           ?
   Position Sizing              ?           ?           ?
   Monte Carlo (100 sims)       ?           ?           ?
   
   (Los resultados arriba revelan si la estrategia es REALMENTE buena
    o solo funcionó por suerte en UN set de datos)
""")

if __name__ == "__main__":
    asyncio.run(main())
