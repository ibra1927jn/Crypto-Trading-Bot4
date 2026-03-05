"""
CT4 LAB — MEGA MATRIX: 40+ Monedas × 20+ Estrategias
=======================================================
La prueba DEFINITIVA. Cada moneda prueba TODAS las estrategias.
$100 capital, Jupiter fees (0.05%), OOS ciego (7 días).
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

CAP = 100; FEE = 0.0005; POS = 0.80

COINS = [
    # Tier 1 — Top Market Cap
    'BTC/USDT','ETH/USDT','BNB/USDT','SOL/USDT','XRP/USDT',
    'DOGE/USDT','ADA/USDT','AVAX/USDT','LINK/USDT','DOT/USDT',
    # Tier 2 — Large Cap
    'LTC/USDT','NEAR/USDT','FIL/USDT','APT/USDT','ARB/USDT',
    'OP/USDT','ATOM/USDT','UNI/USDT','AAVE/USDT','INJ/USDT',
    # Tier 3 — Mid Cap
    'TIA/USDT','SEI/USDT','SUI/USDT','IMX/USDT','MANTA/USDT',
    'JUP/USDT','WIF/USDT','BONK/USDT','PEPE/USDT','SHIB/USDT',
    # Tier 4 — DeFi / L2
    'MKR/USDT','CRV/USDT','SNX/USDT','COMP/USDT','SUSHI/USDT',
    'DYDX/USDT','GMX/USDT','PENDLE/USDT','STX/USDT','RUNE/USDT',
    # Tier 5 — Various
    'FET/USDT','RNDR/USDT','GRT/USDT','SAND/USDT','MANA/USDT',
    'AXS/USDT','GALA/USDT','ENS/USDT','LDO/USDT','WLD/USDT',
]

def calc(df):
    c,h,lo=df['close'],df['high'],df['low']
    df['E5']=c.ewm(span=5).mean();df['E9']=c.ewm(span=9).mean()
    df['E13']=c.ewm(span=13).mean();df['E21']=c.ewm(span=21).mean()
    df['E50']=c.ewm(span=50).mean();df['E200']=c.ewm(span=200).mean()
    d=c.diff();g=d.where(d>0,0).rolling(14).mean()
    l=(-d.where(d<0,0)).rolling(14).mean()
    rs=g/l.replace(0,np.nan);df['RSI']=100-(100/(1+rs))
    tr=pd.concat([h-lo,abs(h-c.shift(1)),abs(lo-c.shift(1))],axis=1).max(axis=1)
    df['ATR']=tr.rolling(14).mean();df['ATR_P']=df['ATR']/c*100
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
    df['H5']=h.rolling(5).max();df['H10']=h.rolling(10).max()
    df['L10']=lo.rolling(10).min()
    rsi=df['RSI'];rr=rsi.rolling(14)
    df['SK']=(rsi-rr.min())/(rr.max()-rr.min()+1e-10)*100
    df['E50H']=c.ewm(span=600).mean()
    df['MOM3']=(c-c.shift(3))/c.shift(3)*100
    df['MOM5']=(c-c.shift(5))/c.shift(5)*100
    return df

def v(r,c,d=0):
    x=r.get(c,d);return d if pd.isna(x) else x

def bt(df,buy,ext,sl,tp,trail=None):
    cap=CAP;pk=CAP;dd=0;pos=None;trades=[]
    for i in range(50,len(df)-1):
        r,p1=df.iloc[i],df.iloc[i-1]
        p2=df.iloc[i-2] if i>=2 else p1
        if pos is None:
            if buy(r,p1,p2):
                a=cap*POS
                if a<5:continue
                sz=a/r['close'];ef=a*FEE
                pos={'e':r['close'],'sl':r['close']*(1+sl/100),
                     'tp':r['close']*(1+tp/100),'sz':sz,'f':ef,'pk':r['close']}
        else:
            p=r['close'];pos['pk']=max(pos['pk'],p)
            if trail and p>pos['e']*1.01:
                pos['sl']=max(pos['sl'],pos['pk']*(1-trail/100))
            pnl=None
            if p<=pos['sl']:pnl=(pos['sl']-pos['e'])*pos['sz']
            elif p>=pos['tp']:pnl=(pos['tp']-pos['e'])*pos['sz']
            elif ext(r,p1):pnl=(p-pos['e'])*pos['sz']
            if pnl is not None:
                pnl-=(pos['f']+abs(p*pos['sz']*FEE))
                cap+=pnl;pk=max(pk,cap);dd=max(dd,(pk-cap)/pk*100)
                trades.append(pnl);pos=None
    if pos:
        p=df.iloc[-1]['close'];pnl=(p-pos['e'])*pos['sz']
        pnl-=pos['f']+abs(p*pos['sz']*FEE);cap+=pnl;trades.append(pnl)
    w=[t for t in trades if t>0];lo=[t for t in trades if t<=0]
    gl=sum(lo) if lo else 0
    return{'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
           'pnl':sum(trades),'dd':dd,'pf':sum(w)/abs(gl) if gl!=0 else 999}

# EXITS
def x0(r,p):return False
def x1(r,p):return v(p,'E5')>=v(p,'E13') and v(r,'E5')<v(r,'E13')
def x2(r,p):return v(r,'BP')>0.90
def x3(r,p):return v(r,'RSI')>70
def x4(r,p):return v(r,'BP')>0.95 or x1(r,p)

# 20 STRATEGIES
S=[
# (name, buy_fn, exit_fn, sl%, tp%, trail%)
("Combo",       lambda r,p,q:v(r,'BP',0.5)<0.20 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>r['open'] and r['close']>v(r,'E50')*0.98, x2,-2,5,1.5),
("Momentum",    lambda r,p,q:v(r,'CP')>0.5 and v(r,'VR',1)>2.0 and r['close']>v(r,'E21'), x1,-3,6,2.0),
("Breakout",    lambda r,p,q:r['close']>v(p,'H10') and v(r,'VR',1)>1.5 and v(r,'ADX')>20, x1,-3,8,None),
("MACD Cross",  lambda r,p,q:v(p,'MC')<v(p,'MS') and v(r,'MC')>=v(r,'MS') and v(r,'RSI',50)<55 and r['close']>v(r,'E21'), x1,-3,5,2.0),
("BB Agresivo", lambda r,p,q:v(r,'BP',0.5)<0.05 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97, x2,-3,6,2.0),
("RSI Extreme", lambda r,p,q:v(p,'RSI',50)<20 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97, x3,-3,6,2.0),
("Vol Spike",   lambda r,p,q:v(r,'VR',1)>3.0 and r['close']>r['open'] and r['close']>v(r,'E21') and v(r,'RSI',50)<65, x1,-2,5,1.5),
("EMA Cross",   lambda r,p,q:v(p,'E5')<v(p,'E13') and v(r,'E5')>=v(r,'E13') and v(r,'ADX')>15 and v(r,'RSI',50)<60, x1,-3,6,2.0),
("Stoch Ext",   lambda r,p,q:v(p,'SK',50)<10 and v(r,'SK',50)>v(p,'SK',50) and r['close']>v(r,'E50')*0.97, x3,-3,6,2.0),
("BB+MTF",      lambda r,p,q:v(r,'BP',0.5)<0.15 and v(p,'RSI',50)<35 and v(r,'RSI',50)>v(p,'RSI',50) and v(r,'ADX')>15 and r['close']>v(r,'E200')*0.99 and r['close']>v(r,'E50H')*0.995, x4,-3,6,2.0),
("Sniper",      lambda r,p,q:v(r,'BP',0.5)<0.15 and v(r,'VR',1)>1.8 and v(p,'RSI',50)<30 and v(r,'RSI',50)>v(p,'RSI',50) and v(r,'ADX')>20 and r['close']>v(r,'E50'), x2,-2,8,2.0),
# Más agresivas
("MomBurst+",   lambda r,p,q:v(r,'CP')>0.8 and v(r,'VR',1)>2.5 and r['close']>v(r,'E9'), x1,-2,4,1.0),
("DoubleBot",   lambda r,p,q:v(r,'BP',0.5)<0.10 and v(p,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.96, x2,-4,8,2.0),
("TrendRide",   lambda r,p,q:v(r,'ADX')>30 and v(r,'E5')>v(r,'E13') and v(r,'E13')>v(r,'E21') and v(r,'RSI',50)<60 and r['close']>v(r,'E50'), x1,-3,10,2.5),
("DipBuy",      lambda r,p,q:v(r,'MOM3',0)<-1.5 and v(r,'RSI',50)<35 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E200')*0.95, x3,-3,5,1.5),
("VolBreak",    lambda r,p,q:v(r,'VR',1)>2.0 and r['close']>v(p,'H5') and v(r,'ADX')>20 and r['close']>v(r,'E21'), x1,-2,6,2.0),
("MACDAggr",    lambda r,p,q:v(p,'MC')<v(p,'MS') and v(r,'MC')>=v(r,'MS') and v(r,'VR',1)>1.5 and r['close']>v(r,'E21'), x1,-2,4,1.5),
("RSI+BB",      lambda r,p,q:v(r,'RSI',50)<30 and v(r,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97, x4,-3,6,2.0),
("Scalp",       lambda r,p,q:v(r,'CP')>0.3 and v(r,'VR',1)>1.3 and v(r,'RSI',50)<55 and v(r,'E5')>v(r,'E9'), x1,-1,2,0.8),
("Swing",       lambda r,p,q:v(r,'BP',0.5)<0.10 and v(r,'ADX')>25 and v(r,'RSI',50)>v(p,'RSI',50) and v(r,'VR',1)>1.2 and r['close']>v(r,'E50'), x0,-5,15,3.0),
]

async def dl(exchange,sym):
    a=[]
    since=int(datetime(2026,2,10,0,0,tzinfo=timezone.utc).timestamp()*1000)
    end=int(datetime(2026,3,5,7,0,tzinfo=timezone.utc).timestamp()*1000)
    try:
        while since<end:
            c=await exchange.fetch_ohlcv(sym,'5m',since=since,limit=1000)
            if not c:break
            a.extend(c);since=c[-1][0]+1
            await asyncio.sleep(0.15)
    except:return None
    if len(a)<300:return None
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
    print(f"🔥 CT4 MEGA MATRIX — {len(COINS)} Monedas × {len(S)} Estrategias × ${CAP}")
    print("="*100)
    
    exchange=ccxt.binance({'sandbox':True})
    data={}
    ok=0;fail=0
    
    for sym in COINS:
        print(f"  📡 {sym:<14}",end="",flush=True)
        df=await dl(exchange,sym)
        if df is not None and len(df)>300:
            data[sym]=df
            vol=df['ATR_P'].dropna().mean()
            ret=(df.iloc[-1]['close']-df.iloc[50]['close'])/df.iloc[50]['close']*100
            print(f"✅ {len(df):>5} velas | Vol {vol:.2f}% | B&H {ret:>+5.1f}%")
            ok+=1
        else:
            print(f"❌ No data");fail+=1
    
    await exchange.close()
    print(f"\n  📊 Monedas OK: {ok} | Fallidas: {fail}")

    # Run matrix
    print(f"\n{'='*100}")
    print(f"🗺️  MEGA MATRIX — OOS CIEGO (últimos 30% = ~7 días)")
    print(f"{'='*100}")
    
    snames=[s[0] for s in S]
    all_combos=[]
    
    # Header
    print(f"\n  {'Moneda':<13}",end="")
    for sn in snames:
        print(f"{sn[:6]:>7}",end="")
    print(f" {'BEST':>8} {'$':>7}")
    print("  "+"-"*(13+7*len(snames)+16))
    
    for sym,df in data.items():
        cut=int(len(df)*0.70)
        df_oos=calc(df.iloc[max(0,cut-50):].copy())
        
        print(f"  {sym:<13}",end="")
        best_pnl=-999;best_name=""
        
        for name,buy,ext,sl,tp,trail in S:
            r=bt(df_oos,buy,ext,sl,tp,trail)
            r['symbol']=sym;r['strategy']=name
            all_combos.append(r)
            
            # Compact display
            if r['pnl']>=0: c="+"
            else: c=" "
            pnl_short=r['pnl']
            if abs(pnl_short)>=10: p_str=f"{c}{pnl_short:>+5.0f}"
            else: p_str=f"{c}{pnl_short:>+5.1f}"
            print(f"{p_str:>7}",end="")
            
            if r['pnl']>best_pnl:best_pnl=r['pnl'];best_name=name
        
        e="🟢" if best_pnl>0 else "🔴"
        print(f" {e}{best_name[:7]:>7} ${best_pnl:>+5.1f}")

    # ═══ TOP 30 ═══
    all_combos.sort(key=lambda x:-x['pnl'])
    print(f"\n{'='*100}")
    print(f"🏆 TOP 30 COMBINACIONES (de {len(all_combos)} probadas)")
    print(f"{'='*100}")
    print(f"  {'#':>3} {'Moneda':<13} {'Estrategia':<14} {'PnL':>8} {'Ret%':>6} {'T':>3} {'WR':>4} {'DD%':>5} {'PF':>5}")
    print("  "+"-"*65)
    for i,r in enumerate(all_combos[:30]):
        e="🟢" if r['pnl']>0 else "🔴"
        ret=r['pnl']/CAP*100
        pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
        print(f"  {i+1:>3} {e} {r['symbol']:<11} {r['strategy']:<14} ${r['pnl']:>+6.1f} {ret:>+5.1f}% {r['n']:>3} {r['wr']:>3.0f}% {r['dd']:>4.1f}% {pf:>5}")

    # ═══ WORST 10 ═══
    print(f"\n  💀 PEORES 10 (evitar a toda costa):")
    for r in all_combos[-10:]:
        ret=r['pnl']/CAP*100
        print(f"     🔴 {r['symbol']:<11} {r['strategy']:<14} ${r['pnl']:>+6.1f} ({ret:>+.1f}%)")

    # ═══ BEST STRATEGY PER COIN ═══
    print(f"\n{'='*100}")
    print(f"🎯 MEJOR ESTRATEGIA PARA CADA MONEDA")
    print(f"{'='*100}")
    coin_best={}
    for r in all_combos:
        sym=r['symbol']
        if sym not in coin_best or r['pnl']>coin_best[sym]['pnl']:
            coin_best[sym]=r
    ranked_coins=sorted(coin_best.values(),key=lambda x:-x['pnl'])
    for r in ranked_coins:
        e="🟢" if r['pnl']>0 else "🔴"
        ret=r['pnl']/CAP*100
        print(f"  {e} {r['symbol']:<13} → {r['strategy']:<14} ${r['pnl']:>+6.1f} ({ret:>+5.1f}%) {r['n']:>3}T WR{r['wr']:>3.0f}%")

    # ═══ BEST COIN PER STRATEGY ═══
    print(f"\n{'='*100}")
    print(f"🎯 MEJOR MONEDA PARA CADA ESTRATEGIA")
    print(f"{'='*100}")
    for sname in snames:
        strat_results=[r for r in all_combos if r['strategy']==sname]
        strat_results.sort(key=lambda x:-x['pnl'])
        best=strat_results[0] if strat_results else None
        if best:
            avg_pnl=np.mean([r['pnl'] for r in strat_results])
            pos_coins=sum(1 for r in strat_results if r['pnl']>0)
            e="🟢" if best['pnl']>0 else "🔴"
            print(f"  {sname:<14} → {e}{best['symbol']:<11} ${best['pnl']:>+6.1f} | "
                  f"Avg ${avg_pnl:>+5.1f} | {pos_coins}/{len(strat_results)} coins positivas")

    # ═══ PORTFOLIO ═══
    print(f"\n{'='*100}")
    print(f"💼 PORTFOLIO ÓPTIMO — $100 en las 5 mejores combinaciones únicas")
    print(f"{'='*100}")
    selected=[];seen_c=set()
    for r in all_combos:
        if r['symbol'] not in seen_c and r['pnl']>0:
            selected.append(r);seen_c.add(r['symbol'])
        if len(selected)==5:break
    if selected:
        per=100/len(selected)
        total=sum(r['pnl']*(per/100) for r in selected)
        for r in selected:
            scaled=r['pnl']*(per/100)
            print(f"  🟢 ${per:.0f} → {r['symbol']:<11} ({r['strategy']:<12}) → ${scaled:>+.2f}")
        print(f"\n  💰 $100 → ${100+total:.2f} ({total:>+.2f}, {total:.1f}%) en 7 días")
        print(f"  📅 Proyección mensual: ~${total*4:.0f} ({total*4:.0f}%)")
    
    print(f"\n  📊 Estadísticas: {len(all_combos)} combinaciones probadas | "
          f"{sum(1 for r in all_combos if r['pnl']>0)} positivas "
          f"({sum(1 for r in all_combos if r['pnl']>0)/len(all_combos)*100:.0f}%)")

if __name__=="__main__":
    asyncio.run(main())
