"""
CT4 LAB — ULTRA AGRESIVO: Estrategias de alto riesgo/alto retorno
===================================================================
Nivel de agresividad MÁXIMO:
  - Position size: 95% del capital
  - Leverage simulado: 2x y 3x
  - Pyramiding: añadir a posiciones ganadoras
  - SL ultra-tight o SIN SL
  - Whale detector, gap fill, scalping extremo

Se prueba en las 15 monedas con mejor rendimiento del mega-test anterior.
"""
import asyncio,sys,os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime,timezone

CAP=100; FEE=0.0005  # Jupiter

# Top 15 del mega matrix
COINS=['BONK/USDT','SAND/USDT','NEAR/USDT','FIL/USDT','FET/USDT',
       'APT/USDT','TIA/USDT','ARB/USDT','WIF/USDT','ETH/USDT',
       'LINK/USDT','DOGE/USDT','SOL/USDT','LTC/USDT','XRP/USDT']

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
    df['H5']=h.rolling(5).max();df['H10']=h.rolling(10).max()
    df['L5']=lo.rolling(5).min()
    rsi=df['RSI'];rr=rsi.rolling(14)
    df['SK']=(rsi-rr.min())/(rr.max()-rr.min()+1e-10)*100
    df['MOM1']=(c-c.shift(1))/c.shift(1)*100
    df['MOM3']=(c-c.shift(3))/c.shift(3)*100
    df['GREEN3']=((c>df['open'])&(c.shift(1)>df['open'].shift(1))&(c.shift(2)>df['open'].shift(2))).astype(int)
    df['VR_MAX5']=df['VR'].rolling(5).max()
    return df

def v(r,c,d=0):
    x=r.get(c,d);return d if pd.isna(x) else x

def bt(df,buy,ext,sl,tp,pos_pct=0.95,trail=None,leverage=1):
    cap=CAP;pk=CAP;dd=0;pos=None;trades=[]
    for i in range(50,len(df)-1):
        r,p1=df.iloc[i],df.iloc[i-1]
        p2=df.iloc[i-2] if i>=2 else p1
        p3=df.iloc[i-3] if i>=3 else p2
        if pos is None:
            if buy(r,p1,p2,p3):
                a=cap*pos_pct*leverage
                if a<3:continue
                sz=a/r['close'];ef=a*FEE
                s=r['close']*(1+sl/100) if sl else 0
                t=r['close']*(1+tp/100) if tp else r['close']*10
                pos={'e':r['close'],'sl':s,'tp':t,'sz':sz,'f':ef,'pk':r['close'],'lev':leverage}
        else:
            p=r['close'];pos['pk']=max(pos['pk'],p)
            if trail and p>pos['e']*1.005:
                pos['sl']=max(pos['sl'],pos['pk']*(1-trail/100))
            pnl=None
            if pos['sl']>0 and p<=pos['sl']:pnl=(pos['sl']-pos['e'])*pos['sz']
            elif p>=pos['tp']:pnl=(pos['tp']-pos['e'])*pos['sz']
            elif ext(r,p1,i-50):pnl=(p-pos['e'])*pos['sz']
            # Liquidation check for leverage
            if leverage>1:
                loss_pct=((pos['e']-p)/pos['e'])*100*leverage
                if loss_pct>=90:  # 90% loss = near liquidation
                    pnl=(p-pos['e'])*pos['sz']; pnl=max(pnl,-cap*0.95)
            if pnl is not None:
                pnl-=(pos['f']+abs(p*pos['sz']*FEE))
                pnl=max(pnl,-cap*0.95)  # Can't lose more than capital
                cap+=pnl;pk=max(pk,cap);dd=max(dd,(pk-cap)/pk*100 if pk>0 else 0)
                trades.append(pnl);pos=None
    if pos:
        p=df.iloc[-1]['close'];pnl=(p-pos['e'])*pos['sz']
        pnl-=pos['f']+abs(p*pos['sz']*FEE);cap+=pnl;trades.append(pnl)
    w=[t for t in trades if t>0];lo=[t for t in trades if t<=0]
    gl=sum(lo) if lo else 0
    return{'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
           'pnl':sum(trades),'dd':dd,'pf':sum(w)/abs(gl) if gl!=0 else 999,
           'best':max(trades) if trades else 0,'worst':min(trades) if trades else 0}

# EXITS
def x0(r,p,bars):return False
def x_ema(r,p,bars):return v(p,'E5')>=v(p,'E13') and v(r,'E5')<v(r,'E13')
def x_bb(r,p,bars):return v(r,'BP')>0.90
def x_rsi(r,p,bars):return v(r,'RSI')>70
def x_time20(r,p,bars):return bars>20  # Exit after 20 bars max
def x_time10(r,p,bars):return bars>10
def x_quick(r,p,bars):return bars>5 or v(r,'RSI')>65

# ═══════════════════════════════════════════
# 15 ULTRA-AGGRESSIVE STRATEGIES
# ═══════════════════════════════════════════

S=[
# --- 95% POSITION, TIGHT PLAYS ---
("AllIn RSI<15",
 lambda r,p,q,w:v(p,'RSI',50)<15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.95,
 x_rsi, -4, 8, 0.95, 2.0, 1),

("AllIn BB<0.03",
 lambda r,p,q,w:v(r,'BP',0.5)<0.03 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.95,
 x_bb, -5, 10, 0.95, 2.5, 1),

("AllIn Stoch<5",
 lambda r,p,q,w:v(p,'SK',50)<5 and v(r,'SK',50)>v(p,'SK',50) and r['close']>v(r,'E50')*0.95,
 x_rsi, -4, 8, 0.95, 2.0, 1),

# --- WHALE DETECTOR (Volume 4x+) ---
("Whale Buy",
 lambda r,p,q,w:v(r,'VR',1)>4.0 and r['close']>r['open'] and v(r,'CP')>0.3 and r['close']>v(r,'E21'),
 x_ema, -2, 5, 0.95, 1.5, 1),

("Whale Extreme",
 lambda r,p,q,w:v(r,'VR',1)>5.0 and r['close']>r['open'] and r['close']>v(r,'E9'),
 x_quick, -3, 4, 0.95, 1.0, 1),

# --- REVERSAL CATCHER ---
("CrashBuy -2%",
 lambda r,p,q,w:v(r,'MOM3',0)<-2.0 and v(r,'RSI',50)<25 and v(r,'RSI',50)>v(p,'RSI',50),
 x_rsi, -5, 10, 0.95, 3.0, 1),

("V-Recovery",
 lambda r,p,q,w:v(p,'MOM1',0)<-0.8 and v(r,'MOM1',0)>0.3 and r['close']>r['open'] and v(r,'VR',1)>1.5,
 x_ema, -2, 5, 0.95, 1.5, 1),

# --- MOMENTUM CHAIN ---
("3GreenCandles",
 lambda r,p,q,w:v(r,'GREEN3')==1 and v(r,'VR',1)>1.5 and v(r,'ADX')>20 and v(r,'RSI',50)<60,
 x_ema, -2, 5, 0.95, 1.5, 1),

("MomExplosion",
 lambda r,p,q,w:v(r,'CP')>1.0 and v(r,'VR',1)>3.0 and r['close']>v(r,'H10'),
 x_quick, -2, 3, 0.95, 1.0, 1),

# --- MICRO SCALP (tiny TP, many trades) ---
("MicroScalp",
 lambda r,p,q,w:v(r,'CP')>0.2 and v(r,'VR',1)>1.2 and v(r,'E5')>v(r,'E9'),
 x0, -0.5, 1.0, 0.95, None, 1),

("ScalpBB",
 lambda r,p,q,w:v(r,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>r['open'],
 x0, -1.0, 1.5, 0.95, None, 1),

# --- LEVERAGE 2x ---
("2x RSI Extreme",
 lambda r,p,q,w:v(p,'RSI',50)<20 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x_rsi, -2, 4, 0.80, 1.5, 2),

("2x BB+Vol",
 lambda r,p,q,w:v(r,'BP',0.5)<0.10 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x_bb, -2, 5, 0.80, 1.5, 2),

# --- LEVERAGE 3x ---
("3x Sniper",
 lambda r,p,q,w:v(r,'BP',0.5)<0.08 and v(r,'VR',1)>2.0 and v(p,'RSI',50)<25 and v(r,'RSI',50)>v(p,'RSI',50) and v(r,'ADX')>20 and r['close']>v(r,'E50'),
 x_bb, -1.5, 4, 0.80, 1.0, 3),

("3x MomBurst",
 lambda r,p,q,w:v(r,'CP')>0.8 and v(r,'VR',1)>3.0 and r['close']>v(r,'H5') and r['close']>v(r,'E21'),
 x_quick, -1.5, 3, 0.80, 0.8, 3),
]

# Previous best strategies for comparison
PREV_BEST=[
("★Stoch Ext",
 lambda r,p,q,w:v(p,'SK',50)<10 and v(r,'SK',50)>v(p,'SK',50) and r['close']>v(r,'E50')*0.97,
 x_rsi, -3, 6, 0.80, 2.0, 1),

("★RSI Extreme",
 lambda r,p,q,w:v(p,'RSI',50)<20 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x_rsi, -3, 6, 0.80, 2.0, 1),

("★BB Agresivo",
 lambda r,p,q,w:v(r,'BP',0.5)<0.05 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x_bb, -3, 6, 0.80, 2.0, 1),

("★Combo",
 lambda r,p,q,w:v(r,'BP',0.5)<0.20 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>r['open'] and r['close']>v(r,'E50')*0.98,
 x_bb, -2, 5, 0.80, 1.5, 1),
]

ALL = S + PREV_BEST

async def dl(exchange,sym):
    a=[]
    since=int(datetime(2026,2,10,0,0,tzinfo=timezone.utc).timestamp()*1000)
    end=int(datetime(2026,3,5,7,0,tzinfo=timezone.utc).timestamp()*1000)
    try:
        while since<end:
            c=await exchange.fetch_ohlcv(sym,'5m',since=since,limit=1000)
            if not c:break
            a.extend(c);since=c[-1][0]+1;await asyncio.sleep(0.15)
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
    print(f"⚡ CT4 LAB — ULTRA AGRESIVO: 15 nuevas + 4 mejores anteriores × 15 monedas top")
    print("="*100)
    print(f"  Capital: ${CAP} | Fee: {FEE*100}% (Jupiter)")
    print(f"  Nuevas: 95% position, whale detector, crash buy, leverage 2x/3x, micro-scalp")
    
    exchange=ccxt.binance({'sandbox':True})
    data={}
    for sym in COINS:
        print(f"  📡 {sym:<13}",end="",flush=True)
        df=await dl(exchange,sym)
        if df is not None and len(df)>300:
            data[sym]=df;print(f"✅ {len(df)} velas")
        else:print("❌")
    await exchange.close()
    
    print(f"\n  📊 {len(data)} monedas cargadas")

    # Matrix OOS
    print(f"\n{'='*100}")
    print(f"⚡ MATRIX ULTRA — OOS CIEGO (7 días)")
    print(f"{'='*100}")
    
    snames=[s[0] for s in ALL]
    all_combos=[]
    
    for sym,df in data.items():
        cut=int(len(df)*0.70)
        df_oos=calc(df.iloc[max(0,cut-50):].copy())
        
        print(f"\n  {sym}:")
        results=[]
        for name,buy,ext,sl,tp,pos,trail,lev in ALL:
            r=bt(df_oos,buy,ext,sl,tp,pos_pct=pos,trail=trail,leverage=lev)
            r['symbol']=sym;r['strategy']=name;r['leverage']=lev
            results.append(r);all_combos.append(r)
        
        # Show top 5 and worst for this coin
        results.sort(key=lambda x:-x['pnl'])
        for i,r in enumerate(results[:5]):
            e="🟢" if r['pnl']>0 else "🔴"
            lv=f"({r['leverage']}x)" if r['leverage']>1 else ""
            print(f"    {i+1}. {e} {r['strategy']:<18}{lv:>4} ${r['pnl']:>+7.2f} ({r['pnl']/CAP*100:>+5.1f}%) "
                  f"| {r['n']:>3}T WR{r['wr']:>3.0f}% DD{r['dd']:>4.1f}% "
                  f"| Best ${r['best']:>+5.1f} Worst ${r['worst']:>+5.1f}")
    
    # ═══ TOP 30 OVERALL ═══
    all_combos.sort(key=lambda x:-x['pnl'])
    print(f"\n{'='*100}")
    print(f"🏆 TOP 30 ULTRA — De {len(all_combos)} combinaciones")
    print(f"{'='*100}")
    print(f"  {'#':>3} {'Moneda':<12} {'Estrategia':<18} {'Lev':>3} {'PnL':>8} {'Ret%':>6} {'T':>3} "
          f"{'WR':>4} {'DD%':>5} {'PF':>5} {'Best':>6} {'Worst':>6}")
    print("  "+"-"*88)
    for i,r in enumerate(all_combos[:30]):
        e="🟢" if r['pnl']>0 else "🔴"
        pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
        lv=f"{r['leverage']}x" if r['leverage']>1 else "1x"
        print(f"  {i+1:>3} {e} {r['symbol']:<10} {r['strategy']:<18} {lv:>3} ${r['pnl']:>+6.1f} "
              f"{r['pnl']/CAP*100:>+5.1f}% {r['n']:>3} {r['wr']:>3.0f}% {r['dd']:>4.1f}% "
              f"{pf:>5} ${r['best']:>+5.1f} ${r['worst']:>+5.1f}")

    # NEW vs OLD comparison
    print(f"\n{'='*100}")
    print(f"⚔️  NUEVO vs ANTERIOR — ¿Las ultra-agresivas ganan más?")
    print(f"{'='*100}")
    
    new_results=[r for r in all_combos if not r['strategy'].startswith('★')]
    old_results=[r for r in all_combos if r['strategy'].startswith('★')]
    
    new_top=sorted(new_results, key=lambda x:-x['pnl'])[:5]
    old_top=sorted(old_results, key=lambda x:-x['pnl'])[:5]
    
    print(f"\n  🆕 TOP 5 NUEVAS (ultra-agresivas):")
    for r in new_top:
        lv=f" ({r['leverage']}x)" if r['leverage']>1 else ""
        print(f"     {r['symbol']:<10} {r['strategy']:<18}{lv} → ${r['pnl']:>+.1f} ({r['pnl']/CAP*100:>+.1f}%) DD{r['dd']:.1f}%")
    new_avg=np.mean([r['pnl'] for r in new_results])
    new_pos=sum(1 for r in new_results if r['pnl']>0)
    
    print(f"\n  ★ TOP 5 ANTERIORES (del mega-matrix):")
    for r in old_top:
        print(f"     {r['symbol']:<10} {r['strategy']:<18}     → ${r['pnl']:>+.1f} ({r['pnl']/CAP*100:>+.1f}%) DD{r['dd']:.1f}%")
    old_avg=np.mean([r['pnl'] for r in old_results])
    old_pos=sum(1 for r in old_results if r['pnl']>0)
    
    print(f"\n  Promedio NUEVO: ${new_avg:>+.2f} | Positivas: {new_pos}/{len(new_results)} ({new_pos/len(new_results)*100:.0f}%)")
    print(f"  Promedio VIEJO: ${old_avg:>+.2f} | Positivas: {old_pos}/{len(old_results)} ({old_pos/len(old_results)*100:.0f}%)")

    # Risk-adjusted
    print(f"\n{'='*100}")
    print(f"📊 COMPARACIÓN POR TIPO")
    print(f"{'='*100}")
    categories={
        "95% AllIn":[r for r in all_combos if 'AllIn' in r['strategy']],
        "Whale":[r for r in all_combos if 'Whale' in r['strategy']],
        "Crash/Recovery":[r for r in all_combos if 'Crash' in r['strategy'] or 'Recovery' in r['strategy']],
        "MomChain":[r for r in all_combos if 'Green' in r['strategy'] or 'Explosion' in r['strategy']],
        "MicroScalp":[r for r in all_combos if 'Scalp' in r['strategy'] or 'Micro' in r['strategy']],
        "2x Leverage":[r for r in all_combos if r['leverage']==2],
        "3x Leverage":[r for r in all_combos if r['leverage']==3],
        "★ Anteriores":[r for r in all_combos if r['strategy'].startswith('★')],
    }
    print(f"  {'Categoría':<18} {'Avg PnL':>8} {'Best':>8} {'Worst':>8} {'WR':>5} {'Pos/Tot':>8}")
    print("  "+"-"*55)
    for cat,rl in categories.items():
        if not rl:continue
        avg=np.mean([r['pnl'] for r in rl])
        best=max(r['pnl'] for r in rl)
        worst=min(r['pnl'] for r in rl)
        wr=np.mean([r['wr'] for r in rl])
        pos=sum(1 for r in rl if r['pnl']>0)
        print(f"  {cat:<18} ${avg:>+6.1f} ${best:>+6.1f} ${worst:>+6.1f} {wr:>4.0f}% {pos:>3}/{len(rl)}")

    # PORTFOLIO
    print(f"\n{'='*100}")
    print(f"💼 PORTFOLIO ULTRA — $100 en las 5 mejores combinaciones únicas")
    print(f"{'='*100}")
    selected=[];seen_c=set()
    for r in all_combos:
        if r['symbol'] not in seen_c and r['pnl']>0:
            selected.append(r);seen_c.add(r['symbol'])
        if len(selected)==5:break
    if selected:
        per=100/len(selected);total=sum(r['pnl']*(per/100) for r in selected)
        for r in selected:
            sc=r['pnl']*(per/100)
            lv=f" ({r['leverage']}x)" if r['leverage']>1 else ""
            print(f"  🟢 ${per:.0f} → {r['symbol']:<10} ({r['strategy']}{lv}) → ${sc:>+.2f}")
        print(f"\n  💰 $100 → ${100+total:.2f} ({total:>+.2f}, {total/100*100:.1f}%) en 7 días")
        print(f"  📅 Mensual: ~${total*4:.0f} ({total*4/100*100:.0f}%)")

if __name__=="__main__":
    asyncio.run(main())
