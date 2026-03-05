"""
CT4 — Comparación: Estrategia ACTUAL del bot vs las 2 ganadoras
================================================================
¿Qué hubiera pasado con $100 en los últimos 3 meses REALES?
1. BB+MTF en BTC (lo que tenemos ahora en testnet)
2. AllIn RSI<15 en BONK (la #1 del lab real)
3. MomBurst+ en SAND (la #2 del lab real)
"""
import asyncio,sys,os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime,timezone

CAP=100; FEE=0.0005

def calc(df):
    c,h,lo=df['close'],df['high'],df['low']
    df['E5']=c.ewm(span=5).mean();df['E9']=c.ewm(span=9).mean()
    df['E13']=c.ewm(span=13).mean();df['E21']=c.ewm(span=21).mean()
    df['E50']=c.ewm(span=50).mean();df['E200']=c.ewm(span=200).mean()
    d=c.diff();g=d.where(d>0,0).rolling(14).mean()
    l=(-d.where(d<0,0)).rolling(14).mean()
    rs=g/l.replace(0,np.nan);df['RSI']=100-(100/(1+rs))
    tr=pd.concat([h-lo,abs(h-c.shift(1)),abs(lo-c.shift(1))],axis=1).max(axis=1)
    df['ATR']=tr.rolling(14).mean()
    pm=h.diff().where(lambda x:(x>0)&(x>-lo.diff()),0)
    mm=(-lo.diff()).where(lambda x:(x>0)&(x>h.diff()),0)
    pi=100*(pm.rolling(14).mean()/df['ATR']);mi=100*(mm.rolling(14).mean()/df['ATR'])
    dx=100*abs(pi-mi)/(pi+mi);df['ADX']=dx.rolling(14).mean()
    df['VS']=df['volume'].rolling(20).mean()
    df['VR']=df['volume']/df['VS'].replace(0,1)
    bm=c.rolling(20).mean();bs=c.rolling(20).std()
    df['BL']=bm-2*bs;df['BH']=bm+2*bs
    df['BP']=(c-df['BL'])/(df['BH']-df['BL']+1e-10)
    e12=c.ewm(span=12).mean();e26=c.ewm(span=26).mean()
    df['MC']=e12-e26;df['MS']=df['MC'].ewm(span=9).mean()
    df['CP']=(c-df['open'])/df['open']*100
    df['H5']=h.rolling(5).max()
    rsi=df['RSI'];rr=rsi.rolling(14)
    df['SK']=(rsi-rr.min())/(rr.max()-rr.min()+1e-10)*100
    df['E50H']=c.ewm(span=600).mean()
    return df

def v(r,c,d=0):
    x=r.get(c,d);return d if pd.isna(x) else x

def bt(df,buy,ext,sl,tp,pos_pct,trail=None,leverage=1,label=""):
    cap=CAP;pk=CAP;dd=0;pos=None;trades=[];equity=[CAP]
    for i in range(250,len(df)-1):
        r,p1=df.iloc[i],df.iloc[i-1]
        p2=df.iloc[i-2] if i>=2 else p1
        if pos is None:
            if buy(r,p1,p2):
                a=cap*pos_pct*leverage
                if a<3:continue
                sz=a/r['close'];ef=a*FEE
                s=r['close']*(1+sl/100) if sl else 0
                t=r['close']*(1+tp/100) if tp else r['close']*10
                pos={'e':r['close'],'sl':s,'tp':t,'sz':sz,'f':ef,'pk':r['close'],'ts':df.index[i]}
        else:
            p=r['close'];pos['pk']=max(pos['pk'],p)
            if trail and p>pos['e']*1.005:
                pos['sl']=max(pos['sl'],pos['pk']*(1-trail/100))
            pnl=None
            if pos['sl']>0 and p<=pos['sl']:pnl=(pos['sl']-pos['e'])*pos['sz']
            elif p>=pos['tp']:pnl=(pos['tp']-pos['e'])*pos['sz']
            elif ext(r,p1):pnl=(p-pos['e'])*pos['sz']
            if leverage>1:
                loss_pct=((pos['e']-p)/pos['e'])*100*leverage
                if loss_pct>=90:pnl=(p-pos['e'])*pos['sz'];pnl=max(pnl,-cap*0.95)
            if pnl is not None:
                pnl-=(pos['f']+abs(p*pos['sz']*FEE));pnl=max(pnl,-cap*0.95)
                cap+=pnl;pk=max(pk,cap);dd=max(dd,(pk-cap)/pk*100 if pk>0 else 0)
                trades.append({'pnl':pnl,'ts':pos['ts'],'exit':df.index[i]})
                pos=None
        equity.append(cap)
    if pos:
        p=df.iloc[-1]['close'];pnl=(p-pos['e'])*pos['sz']
        pnl-=pos['f']+abs(p*pos['sz']*FEE);cap+=pnl
        trades.append({'pnl':pnl,'ts':pos['ts'],'exit':df.index[-1]})
    w=[t for t in trades if t['pnl']>0];lo=[t for t in trades if t['pnl']<=0]
    gl=sum(t['pnl'] for t in lo) if lo else 0
    return{'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
           'pnl':sum(t['pnl'] for t in trades),'dd':dd,
           'pf':sum(t['pnl'] for t in w)/abs(gl) if gl!=0 else 999,
           'cap':cap,'trades':trades,'equity':equity,'label':label}

# EXITS
def x_bb(r,p):return v(r,'BP')>0.90
def x_ema(r,p):return v(p,'E5')>=v(p,'E13') and v(r,'E5')<v(r,'E13')
def x_rsi(r,p):return v(r,'RSI')>70
def x4(r,p):return v(r,'BP')>0.95 or x_ema(r,p)

# STRATEGY 1: BB+MTF (current bot)
def buy_bbmtf(r,p,q):
    return(v(r,'BP',0.5)<0.15 and v(p,'RSI',50)<35 and v(r,'RSI',50)>v(p,'RSI',50) and
           v(r,'ADX')>15 and r['close']>v(r,'E200')*0.99 and r['close']>v(r,'E50H')*0.995)

# STRATEGY 2: AllIn RSI<15 (real data winner #1)
def buy_allin_rsi(r,p,q):
    return v(p,'RSI',50)<15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.95

# STRATEGY 3: MomBurst+ (real data winner #2)
def buy_momburst(r,p,q):
    return v(r,'CP')>0.8 and v(r,'VR',1)>2.5 and r['close']>v(r,'E9')

# STRATEGY 4: Combo Killer (consistent)
def buy_combo(r,p,q):
    return(v(r,'BP',0.5)<0.20 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and
           r['close']>r['open'] and r['close']>v(r,'E50')*0.98)

async def dl(exchange,sym):
    a=[]
    since=int(datetime(2025,9,1,0,0,tzinfo=timezone.utc).timestamp()*1000)
    end=int(datetime(2026,3,5,9,0,tzinfo=timezone.utc).timestamp()*1000)
    try:
        while since<end:
            try:c=await exchange.fetch_ohlcv(sym,'5m',since=since,limit=1000)
            except:await asyncio.sleep(2);continue
            if not c:break
            a.extend(c);since=c[-1][0]+1;await asyncio.sleep(0.12)
    except:pass
    seen=set();u=[]
    for c in a:
        if c[0] not in seen:seen.add(c[0]);u.append(c)
    u.sort(key=lambda x:x[0])
    df=pd.DataFrame(u,columns=['timestamp','open','high','low','close','volume'])
    df['timestamp']=pd.to_datetime(df['timestamp'],unit='ms')
    df.set_index('timestamp',inplace=True)
    return calc(df)

async def main():
    print("="*100)
    print("⚔️  COMPARACIÓN: Estrategia ACTUAL vs Ganadoras — DATOS REALES")
    print("   Sep 2025 → Mar 2026 (6 meses), OOS ciego últimos 3 meses")
    print("="*100)
    
    exchange=ccxt.binance({'sandbox':False,'enableRateLimit':True})
    
    # Download all needed coins
    coins=['BTC/USDT','BONK/USDT','SAND/USDT','NEAR/USDT','DOGE/USDT']
    data={}
    for sym in coins:
        print(f"  📡 {sym:<13}",end="",flush=True)
        df=await dl(exchange,sym)
        if df is not None and len(df)>1000:
            days=len(df)*5/60/24
            data[sym]=df;print(f"✅ {len(df)} velas ({days:.0f}d)")
        else:print("❌")
    await exchange.close()

    # OOS split
    for sym,df in data.items():
        cut=int(len(df)*0.50)
        data[sym]=calc(df.iloc[max(0,cut-250):].copy())

    strats=[
        # Current bot
        ("ACTUAL: BB+MTF en BTC", 'BTC/USDT', buy_bbmtf, x4, -3, 6, 0.80, 2.0, 1),
        # Also test current on other coins
        ("BB+MTF en BONK", 'BONK/USDT', buy_bbmtf, x4, -3, 6, 0.80, 2.0, 1),
        ("BB+MTF en SAND", 'SAND/USDT', buy_bbmtf, x4, -3, 6, 0.80, 2.0, 1),
        # Winners from real data lab
        ("🏆 AllIn RSI<15 en BONK", 'BONK/USDT', buy_allin_rsi, x_rsi, -4, 8, 0.95, 2.0, 1),
        ("🏆 AllIn RSI<15 en NEAR", 'NEAR/USDT', buy_allin_rsi, x_rsi, -4, 8, 0.95, 2.0, 1),
        ("🏆 MomBurst+ en SAND", 'SAND/USDT', buy_momburst, x_ema, -2, 4, 0.95, 1.0, 1),
        ("🏆 MomBurst+ en DOGE", 'DOGE/USDT', buy_momburst, x_ema, -2, 4, 0.95, 1.0, 1),
        ("🏆 Combo en NEAR", 'NEAR/USDT', buy_combo, x_bb, -2, 5, 0.80, 1.5, 1),
    ]
    
    print(f"\n{'='*100}")
    print(f"📊 RESULTADOS — 3 MESES CIEGOS, DATOS REALES, $100")
    print(f"{'='*100}")
    print(f"  {'Estrategia':<28} {'PnL':>8} {'Ret%':>6} {'Trades':>6} {'WR':>4} {'DD%':>5} {'PF':>5}")
    print("  "+"-"*65)
    
    results=[]
    for name,sym,buy,ext,sl,tp,pos,trail,lev in strats:
        if sym not in data:
            print(f"  ❌ {name} — moneda no disponible");continue
        r=bt(data[sym],buy,ext,sl,tp,pos,trail,lev,name)
        r['name']=name;r['sym']=sym
        results.append(r)
        e="🟢" if r['pnl']>0 else "🔴"
        pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
        print(f"  {e} {name:<28} ${r['pnl']:>+6.1f} {r['pnl']/CAP*100:>+5.1f}% {r['n']:>6} {r['wr']:>3.0f}% "
              f"{r['dd']:>4.1f}% {pf:>5}")

    # B&H comparison
    print(f"\n  📊 Comparación Buy & Hold (mismos 3 meses):")
    for sym,df in data.items():
        p0=df.iloc[250]['close'];p1=df.iloc[-1]['close']
        ret=(p1-p0)/p0*100
        e="🟢" if ret>0 else "🔴"
        print(f"  {e} {sym:<13} B&H: {ret:>+.1f}%")

    # Trade details for winner
    print(f"\n{'='*100}")
    print(f"📝 ÚLTIMOS 10 TRADES de los 3 MEJORES:")
    print(f"{'='*100}")
    results.sort(key=lambda x:-x['pnl'])
    for r in results[:3]:
        print(f"\n  {r['name']} (${r['pnl']:>+.1f}):")
        for t in r['trades'][-10:]:
            e="🟢" if t['pnl']>0 else "🔴"
            print(f"    {e} {str(t['ts'])[:16]} → {str(t['exit'])[:16]} | ${t['pnl']:>+.2f}")

    # RECOMMENDATION
    print(f"\n{'='*100}")
    print(f"💡 RECOMENDACIÓN")
    print(f"{'='*100}")
    curr=[r for r in results if 'ACTUAL' in r['name']]
    new=[r for r in results if '🏆' in r['name']]
    if curr:
        c=curr[0]
        print(f"\n  Estrategia ACTUAL (BB+MTF en BTC):")
        print(f"    PnL 3 meses: ${c['pnl']:>+.1f} ({c['pnl']/CAP*100:.1f}%)")
        print(f"    DD máximo: {c['dd']:.1f}%")
    if new:
        best=max(new,key=lambda x:x['pnl'])
        avg=np.mean([r['pnl'] for r in new])
        print(f"\n  Mejor alternativa ({best['name']}):")
        print(f"    PnL 3 meses: ${best['pnl']:>+.1f} ({best['pnl']/CAP*100:.1f}%)")
        print(f"    Promedio ganadoras: ${avg:>+.1f}")
        print(f"\n  Diferencia: ${best['pnl']-curr[0]['pnl']:>+.1f} a favor de la nueva")

if __name__=="__main__":
    asyncio.run(main())
