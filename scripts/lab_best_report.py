"""
CT4 Lab — Best Strategies Report
==================================
Corre las MEJORES estrategias encontradas contra los datos MÁS RECIENTES.
Genera un resumen detallado de cada una.
"""
import asyncio, sys, os
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
    bb_mid=c.rolling(20).mean(); bs=c.rolling(20).std()
    df['BB_LO']=bb_mid-2*bs; df['BB_HI']=bb_mid+2*bs
    df['BB_PCT']=(c-df['BB_LO'])/(df['BB_HI']-df['BB_LO']+1e-10)
    df['DC_HI']=h.rolling(20).max(); df['DC_LO']=lo.rolling(20).min()
    df['DC_MID']=(df['DC_HI']+df['DC_LO'])/2
    return df

def v(r,c,d=0):
    x=r.get(c,d); return d if pd.isna(x) else x

def backtest(df, name, buy_fn, exit_fn, sl_m=1.5, tp_m=3.0, risk=0.3, trailing=False, adapt_sl=False):
    cap=10000; peak=10000; dd=0; pos=None; trades=[]
    for i in range(202,len(df)-1):
        r,p1,p2=df.iloc[i],df.iloc[i-1],df.iloc[i-2]
        p3=df.iloc[i-3] if i>=3 else p2
        if pos is None:
            if buy_fn(r,p1,p2,p3):
                atr=v(r,'ATR',100); adx=v(r,'ADX',30)
                if adapt_sl:
                    sm=2.5 if adx>50 else 2.0 if adx>35 else 1.5
                    tm=4.0 if adx>50 else 3.5 if adx>35 else 3.0
                else:
                    sm=sl_m; tm=tp_m
                sz=(cap*risk)/r['close']
                pos={'e':r['close'],'sl':r['close']-sm*atr,'tp':r['close']+tm*atr,
                     'sz':sz,'b':i,'pk':r['close'],'ts':r.name if hasattr(r,'name') else i}
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
                trades.append({'pnl':pnl,'t':t,'e':pos['e'],'x':p,'bars':i-pos['b'],
                               'pct':(pnl/(pos['e']*pos['sz']))*100}); pos=None
    if pos:
        pnl=(df.iloc[-1]['close']-pos['e'])*pos['sz']; cap+=pnl
        trades.append({'pnl':pnl,'t':'OPEN','e':pos['e'],'x':df.iloc[-1]['close'],'bars':0,'pct':(pnl/(pos['e']*pos['sz']))*100})
    w=[t for t in trades if t['pnl']>0]; lo=[t for t in trades if t['pnl']<=0]
    return {'name':name,'n':len(trades),'w':len(w),'l':len(lo),
            'wr':len(w)/len(trades)*100 if trades else 0,
            'pnl':sum(t['pnl'] for t in trades),'dd':dd,'cap':cap,
            'pf':sum(t['pnl'] for t in w)/abs(sum(t['pnl'] for t in lo)) if lo and sum(t['pnl'] for t in lo)!=0 else 999,
            'avg_hold':np.mean([t['bars']*5 for t in trades]) if trades else 0,
            'max_win':max([t['pnl'] for t in w]) if w else 0,
            'max_loss':min([t['pnl'] for t in lo]) if lo else 0,
            'details':trades}

def exit_ema(r,p):
    return (v(p,'EMA9')>=v(p,'EMA21') and v(r,'EMA9')<v(r,'EMA21')) or r['close']<v(r,'EMA200')*0.985

# ═══ TOP STRATEGIES ═══

def buy_original(r,p1,p2,p3):
    """A. Original Estricta (la del bot)"""
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

def buy_momentum_trail(r,p1,p2,p3):
    """C. Momentum + Trailing Stop"""
    return buy_momentum(r,p1,p2,p3)

def buy_momentum_sl(r,p1,p2,p3):
    """D. Momentum + SL Adaptativo"""
    return buy_momentum(r,p1,p2,p3)

def buy_donchian(r,p1,p2,p3):
    """E. Donchian Turtle"""
    new_high = r['close'] >= v(r,'DC_HI') * 0.999
    vol_confirm = r['volume'] > v(r,'VSMA')
    trend = v(r,'ADX') > 20
    return new_high and vol_confirm and trend
def exit_donchian(r,p): return r['close'] <= v(r,'DC_MID')

def buy_ultimate(r,p1,p2,p3):
    """F. ULTIMATE (todo combinado)"""
    rsi=v(r,'RSI',50); prsi=v(p1,'RSI',50); p2rsi=v(p2,'RSI',50)
    adx=v(r,'ADX'); atr=v(r,'ATR',100)
    atr_pct=(atr/r['close'])*100; hv=atr_pct>0.5
    if prsi<20 and rsi>prsi and adx>35 and r['close']>r['open']: return True
    rsi_thresh=43 if hv else 38; adx_thresh=15 if hv else 20; mt=0.02 if hv else 0.01
    marea=r['close']>v(r,'EMA200')*(1-mt)
    fuerza=adx>adx_thresh; ballenas=r['volume']>v(r,'VSMA')*0.8
    pb=prsi<rsi_thresh and rsi>prsi; mom=rsi>prsi and prsi>p2rsi
    bb=v(r,'BB_PCT',0.5)<0.35
    return marea and fuerza and ballenas and pb and mom and bb

def buy_bh(r,p1,p2,p3):
    """G. Buy & Hold"""
    return False  # Handled separately

async def main():
    print("="*70)
    print("📊 CT4 LAB — Resumen de las MEJORES estrategias")
    print("="*70)
    
    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv('BTC/USDT', '5m', limit=1000)
    await exchange.close()
    
    df = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc(df)
    hrs = len(df)*5/60
    
    print(f"\n✅ {len(df)} velas ({hrs:.0f}h) | {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")
    print(f"   Rango: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    bh_ret = (df.iloc[-1]['close']-df.iloc[200]['close'])/df.iloc[200]['close']*100
    bh_pnl = 10000 * bh_ret / 100
    print(f"   Buy & Hold: {bh_ret:+.2f}% (${bh_pnl:+.0f})")
    
    configs = [
        ("A. ORIGINAL (bot actual)",      buy_original,      exit_ema,     1.5, 3.0, False, False),
        ("B. MOMENTUM ADAPTATIVA",        buy_momentum,      exit_ema,     1.5, 3.0, False, False),
        ("C. MOMENTUM + Trailing",        buy_momentum_trail,exit_ema,     1.5, 3.0, True,  False),
        ("D. MOMENTUM + SL Adaptativo",   buy_momentum_sl,   exit_ema,     1.5, 3.0, False, True),
        ("E. DONCHIAN TURTLE",            buy_donchian,      exit_donchian,1.5, 3.0, False, False),
        ("F. ULTIMATE (combo total)",     buy_ultimate,      exit_ema,     1.5, 3.0, True,  True),
    ]
    
    results = []
    for name, buy, exit_fn, sl, tp, trail, adapt in configs:
        r = backtest(df, name, buy, exit_fn, sl, tp, trailing=trail, adapt_sl=adapt)
        results.append(r)
    
    # Add Buy & Hold
    results.append({
        'name':'G. BUY & HOLD (referencia)','n':1,'w':1 if bh_pnl>0 else 0,'l':0 if bh_pnl>0 else 1,
        'wr':100 if bh_pnl>0 else 0,'pnl':bh_pnl,'dd':0,'cap':10000+bh_pnl,
        'pf':999,'avg_hold':hrs*60,'max_win':bh_pnl,'max_loss':0,'details':[]
    })
    
    # ═══ RESULTS TABLE ═══
    print(f"\n{'='*70}")
    print(f"📊 RESULTADOS COMPLETOS")
    print(f"{'='*70}")
    print(f"   {'Estrategia':<33} {'T':>3} {'W':>2} {'L':>2} {'WR%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5} {'AvgMin':>6}")
    print("   "+"-"*75)
    for r in results:
        e="🟢" if r['pnl']>0 else ("🔴" if r['pnl']<0 else "⚪")
        print(f"   {e} {r['name']:<31} {r['n']:>3} {r['w']:>2} {r['l']:>2} {r['wr']:>4.0f}% ${r['pnl']:>+8.2f} {r['dd']:>4.1f}% {r['pf']:>5.1f} {r['avg_hold']:>5.0f}m")
    
    # ═══ RANKING ═══
    ranked = sorted(results, key=lambda x: x['pnl'], reverse=True)
    medals=["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣"]
    print(f"\n{'='*70}")
    print("🏆 RANKING")
    print(f"{'='*70}")
    for i,r in enumerate(ranked):
        e="🟢" if r['pnl']>0 else "🔴"
        bar = "█" * max(1, int(max(0, r['pnl'])/20))
        print(f"  {medals[i]} {e} {r['name']:<35} ${r['pnl']:>+8.2f} {bar}")
    
    # ═══ TRADE DETAILS for top 3 ═══
    print(f"\n{'='*70}")
    print("📋 DETALLE DE TRADES — Top 3")
    print(f"{'='*70}")
    
    for r in ranked[:3]:
        if not r['details']: continue
        print(f"\n  📌 {r['name']}")
        print(f"     Trades: {r['n']} | W:{r['w']} L:{r['l']} | WR: {r['wr']:.0f}% | PF: {r['pf']:.1f}")
        print(f"     MaxWin: ${r['max_win']:+.2f} | MaxLoss: ${r['max_loss']:+.2f}")
        for j,t in enumerate(r['details']):
            e="🟢" if t['pnl']>0 else "🔴"
            print(f"     {e} #{j+1} ${t['e']:.0f}→${t['x']:.0f} | {t['t']:>4} | ${t['pnl']:>+7.2f} ({t['pct']:>+5.1f}%) | {t['bars']*5}min")
    
    # ═══ RISK-ADJUSTED ═══
    print(f"\n{'='*70}") 
    print("🛡️ ANÁLISIS RIESGO-RECOMPENSA")
    print(f"{'='*70}")
    print(f"   {'Estrategia':<33} {'PnL':>8} {'DD%':>5} {'PnL/DD':>7} {'Sharpe':>7}")
    print("   "+"-"*65)
    for r in ranked:
        pnl_dd = r['pnl']/r['dd'] if r['dd']>0 else 999
        sharpe = r['pnl']/abs(r['max_loss']) if r['max_loss']!=0 else 999
        print(f"   {r['name']:<33} ${r['pnl']:>+6.0f} {r['dd']:>4.1f}% {pnl_dd:>+6.1f} {sharpe:>+6.1f}")
    
    # ═══ CONCLUSION ═══
    print(f"\n{'='*70}")
    print("💡 CONCLUSIÓN")
    print(f"{'='*70}")
    w = ranked[0]
    orig = results[0]
    print(f"  🏆 Mejor: {w['name']}")
    print(f"     PnL: ${w['pnl']:+.2f} ({w['wr']:.0f}% WR)")
    print(f"  📉 Original: ${orig['pnl']:+.2f} ({orig['wr']:.0f}% WR)")
    if w['pnl'] != 0 and orig['pnl'] != 0:
        mult = w['pnl']/orig['pnl']
        print(f"  📊 Diferencia: ×{mult:.1f}")

if __name__ == "__main__":
    asyncio.run(main())
