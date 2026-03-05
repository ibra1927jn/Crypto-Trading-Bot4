"""
CT4 Lab — THE ULTIMATE: Best of all labs combined
====================================================
Combina los mejores hallazgos de 6 rondas de laboratorio:

  ✅ Momentum Adaptativa (4 leyes flexibles + 2 velas momentum)
  ✅ SL Adaptativo (más espacio si ADX alto)
  ✅ Trailing Stop (SL sube cuando ganas +0.5%)
  ✅ Filtro Bollinger (solo comprar en zona baja <35%)
  ✅ Override RSI extremo (<20)
  ✅ RSI umbral 38 (más oportunidades)

Probado en TRES timeframes: 5min, 15min, 1h
+ Monte Carlo 50 sims
+ Walk-Forward
+ vs TODAS las estrategias anteriores
"""
import asyncio, sys, os, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

def calc(df):
    df['EMA9']=df['close'].ewm(span=9).mean()
    df['EMA21']=df['close'].ewm(span=21).mean()
    df['EMA200']=df['close'].ewm(span=200).mean()
    d=df['close'].diff()
    g=d.where(d>0,0).rolling(14).mean()
    l=(-d.where(d<0,0)).rolling(14).mean()
    rs=g/l.replace(0,np.nan)
    df['RSI']=100-(100/(1+rs))
    h,lo,c=df['high'],df['low'],df['close']
    tr=pd.concat([h-lo,abs(h-c.shift(1)),abs(lo-c.shift(1))],axis=1).max(axis=1)
    df['ATR']=tr.rolling(14).mean()
    pdm=h.diff().where(lambda x:(x>0)&(x>-lo.diff()),0)
    mdm=(-lo.diff()).where(lambda x:(x>0)&(x>h.diff()),0)
    pdi=100*(pdm.rolling(14).mean()/df['ATR'])
    mdi=100*(mdm.rolling(14).mean()/df['ATR'])
    dx=100*abs(pdi-mdi)/(pdi+mdi)
    df['ADX']=dx.rolling(14).mean()
    df['VSMA']=df['volume'].rolling(20).mean()
    bb_mid=c.rolling(20).mean()
    bs=c.rolling(20).std()
    df['BB_LO']=bb_mid-2*bs; df['BB_HI']=bb_mid+2*bs
    df['BB_PCT']=(c-df['BB_LO'])/(df['BB_HI']-df['BB_LO']+1e-10)
    return df

def v(r,c,d=0):
    x=r.get(c,d); return d if pd.isna(x) else x

def backtest(df, buy_fn, exit_fn, sl_fn, tp_fn, trailing=False, risk=0.3):
    cap=10000; peak=10000; dd=0; pos=None; trades=[]
    for i in range(202,len(df)-1):
        r,p1,p2=df.iloc[i],df.iloc[i-1],df.iloc[i-2]
        p3=df.iloc[i-3] if i>=3 else p2
        if pos is None:
            if buy_fn(r,p1,p2,p3):
                atr=v(r,'ATR',100); adx=v(r,'ADX',30)
                sl=sl_fn(r['close'],atr,adx); tp=tp_fn(r['close'],atr,adx)
                sz=(cap*risk)/r['close']
                pos={'e':r['close'],'sl':sl,'tp':tp,'sz':sz,'b':i,'pk':r['close']}
        else:
            p=r['close']; pos['pk']=max(pos['pk'],p)
            if trailing and p>pos['e']*1.005:
                pos['sl']=max(pos['sl'],p-1.0*v(r,'ATR',100))
            pnl=None; t=None
            if p<=pos['sl']: pnl=(pos['sl']-pos['e'])*pos['sz']; t='SL'
            elif p>=pos['tp']: pnl=(pos['tp']-pos['e'])*pos['sz']; t='TP'
            elif exit_fn(r,p1): pnl=(p-pos['e'])*pos['sz']; t='EXIT'
            if pnl is not None:
                cap+=pnl; peak=max(peak,cap); dd=max(dd,(peak-cap)/peak*100)
                trades.append({'pnl':pnl,'t':t,'e':pos['e'],'x':p,'bars':i-pos['b']}); pos=None
    if pos:
        pnl=(df.iloc[-1]['close']-pos['e'])*pos['sz']; cap+=pnl
        trades.append({'pnl':pnl,'t':'OPEN','e':pos['e'],'x':df.iloc[-1]['close'],'bars':0})
    w=[t for t in trades if t['pnl']>0]
    lo=[t for t in trades if t['pnl']<=0]
    return {'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
            'pnl':sum(t['pnl'] for t in trades),'dd':dd,'cap':cap,
            'pf':sum(t['pnl'] for t in w)/abs(sum(t['pnl'] for t in lo)) if lo and sum(t['pnl'] for t in lo)!=0 else 999,
            'details':trades}

# ═══ SL/TP ═══
def sl_fixed(p,a,adx): return p-1.5*a
def tp_fixed(p,a,adx): return p+3.0*a
def sl_adapt(p,a,adx):
    m=2.5 if adx>50 else 2.0 if adx>35 else 1.5
    return p-m*a
def tp_adapt(p,a,adx):
    m=4.0 if adx>50 else 3.5 if adx>35 else 3.0
    return p+m*a

# ═══ EXITS ═══
def exit_base(r,p):
    return (v(p,'EMA9')>=v(p,'EMA21') and v(r,'EMA9')<v(r,'EMA21')) or r['close']<v(r,'EMA200')*0.985

# ═══ STRATEGIES ═══

def buy_original(r,p1,p2,p3):
    """A. Original Estricta"""
    return (r['close']>v(r,'EMA200') and v(r,'ADX')>20 and
            r['volume']>v(r,'VSMA') and v(p1,'RSI')<35 and v(r,'RSI')>v(p1,'RSI'))

def buy_momentum(r,p1,p2,p3):
    """B. Momentum Adaptativa"""
    rsi,prsi,p2rsi=v(r,'RSI',50),v(p1,'RSI',50),v(p2,'RSI',50)
    adx=v(r,'ADX')
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']: return True
    atr_pct=(v(r,'ATR',100)/r['close'])*100; hv=atr_pct>0.5
    rt=40 if hv else 35; at=15 if hv else 20; mt=0.02 if hv else 0.01
    return (r['close']>v(r,'EMA200')*(1-mt) and adx>at and
            r['volume']>v(r,'VSMA')*0.8 and prsi<rt and rsi>prsi and prsi>p2rsi)

def buy_ultimate(r,p1,p2,p3):
    """C. ULTIMATE — Best of everything"""
    rsi=v(r,'RSI',50); prsi=v(p1,'RSI',50); p2rsi=v(p2,'RSI',50)
    adx=v(r,'ADX'); atr=v(r,'ATR',100)
    atr_pct=(atr/r['close'])*100; hv=atr_pct>0.5
    
    # OVERRIDE: RSI extremo + vela verde
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']:
        return True
    
    # Umbrales adaptativos
    rsi_thresh = 43 if hv else 38
    adx_thresh = 15 if hv else 20
    marea_tol = 0.02 if hv else 0.01
    
    # 4 LEYES ADAPTATIVAS
    marea = r['close'] > v(r,'EMA200') * (1 - marea_tol)
    fuerza = adx > adx_thresh
    ballenas = r['volume'] > v(r,'VSMA') * 0.8
    pullback = prsi < rsi_thresh and rsi > prsi
    
    # MOMENTUM: 2 velas consecutivas subiendo
    momentum = rsi > prsi and prsi > p2rsi
    
    # BOLLINGER: precio en zona baja (<35%)
    bb_ok = v(r,'BB_PCT',0.5) < 0.35
    
    return marea and fuerza and ballenas and pullback and momentum and bb_ok

def buy_ultimate_no_bb(r,p1,p2,p3):
    """D. ULTIMATE sin Bollinger"""
    rsi=v(r,'RSI',50); prsi=v(p1,'RSI',50); p2rsi=v(p2,'RSI',50)
    adx=v(r,'ADX'); atr=v(r,'ATR',100)
    atr_pct=(atr/r['close'])*100; hv=atr_pct>0.5
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']: return True
    rsi_thresh = 43 if hv else 38
    adx_thresh = 15 if hv else 20
    marea_tol = 0.02 if hv else 0.01
    marea = r['close'] > v(r,'EMA200') * (1 - marea_tol)
    fuerza = adx > adx_thresh
    ballenas = r['volume'] > v(r,'VSMA') * 0.8
    pullback = prsi < rsi_thresh and rsi > prsi
    momentum = rsi > prsi and prsi > p2rsi
    return marea and fuerza and ballenas and pullback and momentum

def buy_ultimate_rsi35(r,p1,p2,p3):
    """E. ULTIMATE con RSI 35 (más estricto)"""
    rsi=v(r,'RSI',50); prsi=v(p1,'RSI',50); p2rsi=v(p2,'RSI',50)
    adx=v(r,'ADX'); atr=v(r,'ATR',100)
    atr_pct=(atr/r['close'])*100; hv=atr_pct>0.5
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']: return True
    rsi_thresh = 40 if hv else 35
    adx_thresh = 15 if hv else 20
    marea_tol = 0.02 if hv else 0.01
    marea = r['close'] > v(r,'EMA200') * (1 - marea_tol)
    fuerza = adx > adx_thresh
    ballenas = r['volume'] > v(r,'VSMA') * 0.8
    pullback = prsi < rsi_thresh and rsi > prsi
    momentum = rsi > prsi and prsi > p2rsi
    bb_ok = v(r,'BB_PCT',0.5) < 0.35
    return marea and fuerza and ballenas and pullback and momentum and bb_ok

async def main():
    print("="*70)
    print("🏗️ CT4 LAB — THE ULTIMATE STRATEGY BUILD")
    print("="*70)
    
    exchange = ccxt.binance({'sandbox': True})
    dfs = {}
    for tf in ['5m','15m','1h']:
        c = await exchange.fetch_ohlcv('BTC/USDT', tf, limit=1000)
        d = pd.DataFrame(c, columns=['timestamp','open','high','low','close','volume'])
        d['timestamp'] = pd.to_datetime(d['timestamp'], unit='ms')
        d.set_index('timestamp', inplace=True)
        dfs[tf] = calc(d)
        hrs = len(d)*{'5m':5,'15m':15,'1h':60}[tf]/60
        print(f"   ✅ {tf}: {len(d)} velas ({hrs:.0f}h)")
    await exchange.close()
    
    configs = [
        # (name, buy_fn, exit_fn, sl_fn, tp_fn, trailing)
        ("A. Original Estricta",        buy_original,      exit_base, sl_fixed, tp_fixed, False),
        ("B. Momentum Adaptativa",      buy_momentum,      exit_base, sl_fixed, tp_fixed, False),
        ("C. Momentum + SL Adapt",      buy_momentum,      exit_base, sl_adapt, tp_adapt, False),
        ("D. Momentum + Trailing",      buy_momentum,      exit_base, sl_fixed, tp_fixed, True),
        ("E. Momentum + SL + Trail",    buy_momentum,      exit_base, sl_adapt, tp_adapt, True),
        ("F. ULTIMATE (todo)",          buy_ultimate,      exit_base, sl_adapt, tp_adapt, True),
        ("G. ULTIMATE sin BB",          buy_ultimate_no_bb,exit_base, sl_adapt, tp_adapt, True),
        ("H. ULTIMATE RSI35",           buy_ultimate_rsi35,exit_base, sl_adapt, tp_adapt, True),
    ]
    
    # ═══ TEST MULTI-TIMEFRAME ═══
    for tf in ['5m','15m','1h']:
        df = dfs[tf]
        print(f"\n{'='*70}")
        print(f"⏱️ TIMEFRAME: {tf} ({len(df)} velas)")
        print(f"{'='*70}")
        print(f"   {'Estrategia':<30} {'T':>3} {'W':>3} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
        print("   "+"-"*65)
        
        for name, buy, ext, sl, tp, trail in configs:
            r = backtest(df, buy, ext, sl, tp, trail)
            e="🟢" if r['pnl']>0 else ("🔴" if r['pnl']<0 else "⚪")
            print(f"   {e} {name:<28} {r['n']:>3} {r['w']:>3} {r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {r['pf']:>5.1f}")
    
    # ═══ WALK-FORWARD on best timeframe ═══
    print(f"\n{'='*70}")
    print("🛡️ WALK-FORWARD (15min) — 70/30 split")
    print(f"{'='*70}")
    df15 = dfs['15m']
    sp = int(len(df15)*0.7)
    train, test = df15.iloc[:sp], df15.iloc[sp:]
    
    print(f"   {'Estrategia':<30} {'TRAIN':>12} {'TEST':>12} {'OK?':>5}")
    print("   "+"-"*65)
    for name, buy, ext, sl, tp, trail in configs:
        rt = backtest(train, buy, ext, sl, tp, trail)
        rv = backtest(test, buy, ext, sl, tp, trail)
        ok = "✅" if (rt['pnl']>0)==(rv['pnl']>0) else "❌"
        et="🟢" if rt['pnl']>0 else "🔴"
        ev="🟢" if rv['pnl']>0 else "🔴"
        print(f"   {name:<30} {et}${rt['pnl']:>+8.2f} {ev}${rv['pnl']:>+8.2f}  {ok}")
    
    # ═══ MONTE CARLO (50 sims on 15min) ═══
    print(f"\n{'='*70}")
    print("🎲 MONTE CARLO (50 sims, 15min)")
    print(f"{'='*70}")
    
    for name, buy, ext, sl, tp, trail in configs:
        profits = []
        for _ in range(50):
            blocks = [df15.iloc[i:i+5] for i in range(0, len(df15), 5)]
            random.shuffle(blocks)
            sh = pd.concat(blocks).reset_index(drop=True)
            sh = calc(sh)
            r = backtest(sh, buy, ext, sl, tp, trail)
            profits.append(r['pnl'])
        wins = sum(1 for p in profits if p > 0)
        avg = np.mean(profits)
        worst = min(profits)
        best = max(profits)
        e="🟢" if wins>=25 else "🔴"
        print(f"   {e} {name:<28} {wins:>2}/50 ({wins*2:>3}%) | Avg:${avg:>+7.0f} | Worst:${worst:>+7.0f} | Best:${best:>+7.0f}")
    
    # ═══ FINAL COMPARISON ═══
    print(f"\n{'='*70}")
    print("🏆 TABLA FINAL — Todas las métricas combinadas (15min)")
    print(f"{'='*70}")
    
    df15 = dfs['15m']
    final = []
    for name, buy, ext, sl, tp, trail in configs:
        r = backtest(df15, buy, ext, sl, tp, trail)
        # Walk-forward
        rt = backtest(train, buy, ext, sl, tp, trail)
        rv = backtest(test, buy, ext, sl, tp, trail)
        wf = rv['pnl']
        r['name'] = name
        r['wf'] = wf
        final.append(r)
    
    ranked = sorted(final, key=lambda x: x['pnl'], reverse=True)
    medals=["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    print(f"   {'#':<3} {'Estrategia':<30} {'PnL':>8} {'WR%':>5} {'PF':>5} {'DD%':>5} {'WF PnL':>8}")
    print("   "+"-"*70)
    for i,r in enumerate(ranked):
        e="🟢" if r['pnl']>0 else "🔴"
        wfe="🟢" if r['wf']>0 else "🔴"
        print(f"   {medals[i]} {e}{r['name']:<29} ${r['pnl']:>+6.0f} {r['wr']:>4.0f}% {r['pf']:>5.1f} {r['dd']:>4.1f}% {wfe}${r['wf']:>+6.0f}")
    
    w = ranked[0]
    print(f"\n⭐ CAMPEONA ABSOLUTA: {w['name']}")
    print(f"   PnL: ${w['pnl']:+.2f} | WR: {w['wr']:.0f}% | PF: {w['pf']:.1f} | DD: {w['dd']:.1f}%")
    print(f"   Walk-Forward: ${w['wf']:+.2f}")
    for t in w['details'][:10]:
        e="🟢" if t['pnl']>0 else "🔴"
        print(f"   {e} ${t['e']:.0f}→${t['x']:.0f} | {t['t']:>4} | ${t['pnl']:+.2f} | {t['bars']*15}min")

if __name__ == "__main__":
    asyncio.run(main())
