"""
CT4 LAB — TEST CIEGO LARGO: 2+ meses de datos
=================================================
VALIDACIÓN DEFINITIVA.

Datos: Dic 1 2025 → Mar 5 2026 (~95 días)
Split: 30% warmup (28 días) | 70% CIEGO (67 días)

Top 20 estrategias de TODOS los labs anteriores.
Top 12 monedas con mejor rendimiento.
$100 capital, Jupiter fees (0.05%).
"""
import asyncio,sys,os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime,timezone

CAP=100; FEE=0.0005; POS80=0.80; POS95=0.95

COINS=['BONK/USDT','SAND/USDT','NEAR/USDT','FIL/USDT','TIA/USDT',
       'APT/USDT','FET/USDT','LINK/USDT','ETH/USDT','DOGE/USDT',
       'SOL/USDT','XRP/USDT']

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
    rsi=df['RSI'];rr=rsi.rolling(14)
    df['SK']=(rsi-rr.min())/(rr.max()-rr.min()+1e-10)*100
    df['MOM1']=(c-c.shift(1))/c.shift(1)*100
    df['MOM3']=(c-c.shift(3))/c.shift(3)*100
    df['E50H']=c.ewm(span=600).mean()
    return df

def v(r,c,d=0):
    x=r.get(c,d);return d if pd.isna(x) else x

def bt(df,buy,ext,sl,tp,pos_pct,trail=None,leverage=1):
    cap=CAP;pk=CAP;dd=0;pos=None;trades=[];equity=[CAP]
    for i in range(50,len(df)-1):
        r,p1=df.iloc[i],df.iloc[i-1]
        p2=df.iloc[i-2] if i>=2 else p1
        if pos is None:
            if buy(r,p1,p2):
                a=cap*pos_pct*leverage
                if a<3:continue
                sz=a/r['close'];ef=a*FEE
                s=r['close']*(1+sl/100) if sl else 0
                t=r['close']*(1+tp/100) if tp else r['close']*10
                pos={'e':r['close'],'sl':s,'tp':t,'sz':sz,'f':ef,'pk':r['close']}
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
                trades.append(pnl);pos=None
        equity.append(cap)
    if pos:
        p=df.iloc[-1]['close'];pnl=(p-pos['e'])*pos['sz']
        pnl-=pos['f']+abs(p*pos['sz']*FEE);cap+=pnl;trades.append(pnl)
    w=[t for t in trades if t>0];lo=[t for t in trades if t<=0]
    gl=sum(lo) if lo else 0
    # Monthly breakdown
    monthly=[]
    if len(equity)>1:
        month_cap=CAP
        for i in range(0,len(equity),288*30):  # ~30 days of 5m bars
            end_i=min(i+288*30,len(equity)-1)
            m_pnl=equity[end_i]-equity[i]
            monthly.append(m_pnl)
    # Longest winning/losing streak
    mcl=0;mwl=0;cl=0;wl=0
    for t in trades:
        if t<=0:cl+=1;wl=0;mcl=max(mcl,cl)
        else:wl+=1;cl=0;mwl=max(mwl,wl)
    return{'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
           'pnl':sum(trades),'dd':dd,'pf':sum(w)/abs(gl) if gl!=0 else 999,
           'cap':cap,'mcl':mcl,'mwl':mwl,'monthly':monthly,
           'avg':np.mean(trades) if trades else 0}

# EXITS
def x0(r,p):return False
def x1(r,p):return v(p,'E5')>=v(p,'E13') and v(r,'E5')<v(r,'E13')
def x2(r,p):return v(r,'BP')>0.90
def x3(r,p):return v(r,'RSI')>70
def x4(r,p):return v(r,'BP')>0.95 or x1(r,p)

# TOP 20 STRATEGIES from ALL labs
S=[
# (name, buy, exit, sl, tp, pos%, trail, leverage)
("2x RSI Extreme",
 lambda r,p,q:v(p,'RSI',50)<20 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x3, -2, 4, POS80, 1.5, 2),

("2x BB+Vol",
 lambda r,p,q:v(r,'BP',0.5)<0.10 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x2, -2, 5, POS80, 1.5, 2),

("AllIn Stoch<5",
 lambda r,p,q:v(p,'SK',50)<5 and v(r,'SK',50)>v(p,'SK',50) and r['close']>v(r,'E50')*0.95,
 x3, -4, 8, POS95, 2.0, 1),

("AllIn RSI<15",
 lambda r,p,q:v(p,'RSI',50)<15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.95,
 x3, -4, 8, POS95, 2.0, 1),

("AllIn BB<0.03",
 lambda r,p,q:v(r,'BP',0.5)<0.03 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.95,
 x2, -5, 10, POS95, 2.5, 1),

("Stoch Extreme",
 lambda r,p,q:v(p,'SK',50)<10 and v(r,'SK',50)>v(p,'SK',50) and r['close']>v(r,'E50')*0.97,
 x3, -3, 6, POS80, 2.0, 1),

("RSI Extreme",
 lambda r,p,q:v(p,'RSI',50)<20 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x3, -3, 6, POS80, 2.0, 1),

("BB Agresivo",
 lambda r,p,q:v(r,'BP',0.5)<0.05 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x2, -3, 6, POS80, 2.0, 1),

("Combo Killer",
 lambda r,p,q:v(r,'BP',0.5)<0.20 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>r['open'] and r['close']>v(r,'E50')*0.98,
 x2, -2, 5, POS80, 1.5, 1),

("Momentum",
 lambda r,p,q:v(r,'CP')>0.5 and v(r,'VR',1)>2.0 and r['close']>v(r,'E21'),
 x1, -3, 6, POS80, 2.0, 1),

("Breakout",
 lambda r,p,q:r['close']>v(p,'H10') and v(r,'VR',1)>1.5 and v(r,'ADX')>20,
 x1, -3, 8, POS80, None, 1),

("MACD Cross",
 lambda r,p,q:v(p,'MC')<v(p,'MS') and v(r,'MC')>=v(r,'MS') and v(r,'RSI',50)<55 and r['close']>v(r,'E21'),
 x1, -3, 5, POS80, 2.0, 1),

("VolBreak",
 lambda r,p,q:v(r,'VR',1)>2.0 and r['close']>v(p,'H5') and v(r,'ADX')>20 and r['close']>v(r,'E21'),
 x1, -2, 6, POS80, 2.0, 1),

("MomBurst+",
 lambda r,p,q:v(r,'CP')>0.8 and v(r,'VR',1)>2.5 and r['close']>v(r,'E9'),
 x1, -2, 4, POS95, 1.0, 1),

("DoubleBot",
 lambda r,p,q:v(r,'BP',0.5)<0.10 and v(p,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.96,
 x2, -4, 8, POS80, 2.0, 1),

("TrendRide",
 lambda r,p,q:v(r,'ADX')>30 and v(r,'E5')>v(r,'E13') and v(r,'E13')>v(r,'E21') and v(r,'RSI',50)<60 and r['close']>v(r,'E50'),
 x1, -3, 10, POS80, 2.5, 1),

("RSI+BB",
 lambda r,p,q:v(r,'RSI',50)<30 and v(r,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x4, -3, 6, POS80, 2.0, 1),

("V-Recovery",
 lambda r,p,q:v(p,'MOM1',0)<-0.8 and v(r,'MOM1',0)>0.3 and r['close']>r['open'] and v(r,'VR',1)>1.5,
 x1, -2, 5, POS95, 1.5, 1),

("BB+MTF",
 lambda r,p,q:v(r,'BP',0.5)<0.15 and v(p,'RSI',50)<35 and v(r,'RSI',50)>v(p,'RSI',50) and v(r,'ADX')>15 and r['close']>v(r,'E200')*0.99 and r['close']>v(r,'E50H')*0.995,
 x4, -3, 6, POS80, 2.0, 1),

("DipBuy",
 lambda r,p,q:v(r,'MOM3',0)<-1.5 and v(r,'RSI',50)<35 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E200')*0.95,
 x3, -3, 5, POS80, 1.5, 1),
]

async def dl(exchange,sym,start_date):
    a=[]
    since=int(start_date.timestamp()*1000)
    end=int(datetime(2026,3,5,8,0,tzinfo=timezone.utc).timestamp()*1000)
    try:
        while since<end:
            c=await exchange.fetch_ohlcv(sym,'5m',since=since,limit=1000)
            if not c:break
            a.extend(c);since=c[-1][0]+1;await asyncio.sleep(0.12)
    except:return None
    if len(a)<500:return None
    seen=set();u=[]
    for c in a:
        if c[0] not in seen:seen.add(c[0]);u.append(c)
    u.sort(key=lambda x:x[0])
    df=pd.DataFrame(u,columns=['timestamp','open','high','low','close','volume'])
    df['timestamp']=pd.to_datetime(df['timestamp'],unit='ms')
    df.set_index('timestamp',inplace=True)
    return calc(df)

async def main():
    start_date=datetime(2025,12,1,0,0,tzinfo=timezone.utc)
    print("="*100)
    print(f"🧪 CT4 LAB — TEST CIEGO LARGO: ~3 meses de datos")
    print(f"   Dic 1 2025 → Mar 5 2026 (~95 días)")
    print(f"   Top 20 estrategias × 12 monedas = 240 combinaciones")
    print(f"   Split: 30% warmup | 70% CIEGO (~67 días)")
    print("="*100)

    exchange=ccxt.binance({'sandbox':True})
    data={}
    for sym in COINS:
        print(f"  📡 {sym:<13}",end="",flush=True)
        df=await dl(exchange,sym,start_date)
        if df is not None and len(df)>500:
            days=len(df)*5/60/24
            ret=(df.iloc[-1]['close']-df.iloc[200]['close'])/df.iloc[200]['close']*100
            data[sym]=df
            print(f"✅ {len(df):>6} velas ({days:.0f} días) | B&H {ret:>+.1f}%")
        else:
            print(f"❌ Insuficiente")
    await exchange.close()

    print(f"\n  📊 {len(data)} monedas cargadas")

    # Matrix
    all_combos=[]
    for sym,df in data.items():
        cut=int(len(df)*0.30)  # 30% warmup, 70% blind
        df_oos=calc(df.iloc[max(0,cut-50):].copy())
        oos_days=len(df_oos)*5/60/24
        
        print(f"\n{'='*100}")
        print(f"📊 {sym} — OOS CIEGO: {oos_days:.0f} días ({len(df_oos)} velas)")
        print(f"{'='*100}")
        print(f"  {'Estrategia':<18} {'Lev':>3} {'PnL':>8} {'Ret%':>6} {'T':>4} {'WR':>4} {'DD%':>5} "
              f"{'PF':>5} {'AvgT':>6} {'MCL':>3} {'MWL':>3}")
        print("  "+"-"*75)
        
        for name,buy,ext,sl,tp,pos,trail,lev in S:
            r=bt(df_oos,buy,ext,sl,tp,pos,trail,lev)
            r['symbol']=sym;r['strategy']=name;r['leverage']=lev
            all_combos.append(r)
            e="🟢" if r['pnl']>0 else "🔴"
            pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
            lv=f"{lev}x" if lev>1 else "  "
            print(f"  {e} {name:<18} {lv:>3} ${r['pnl']:>+6.1f} {r['pnl']/CAP*100:>+5.1f}% {r['n']:>4} "
                  f"{r['wr']:>3.0f}% {r['dd']:>4.1f}% {pf:>5} ${r['avg']:>+4.2f} {r['mcl']:>3} {r['mwl']:>3}")

    # ═══ OVERALL RANKING ═══
    all_combos.sort(key=lambda x:-x['pnl'])
    print(f"\n{'='*100}")
    print(f"🏆 TOP 30 — TEST CIEGO ~67 días ({len(all_combos)} combinaciones)")
    print(f"{'='*100}")
    print(f"  {'#':>3} {'Moneda':<12} {'Estrategia':<18} {'L':>2} {'PnL':>8} {'Ret%':>6} {'T':>4} "
          f"{'WR':>4} {'DD%':>5} {'PF':>5} {'MCL':>3}")
    print("  "+"-"*78)
    for i,r in enumerate(all_combos[:30]):
        e="🟢" if r['pnl']>0 else "🔴"
        pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
        lv=f"{r['leverage']}x" if r['leverage']>1 else "  "
        print(f"  {i+1:>3} {e} {r['symbol']:<10} {r['strategy']:<18} {lv:>2} ${r['pnl']:>+6.1f} "
              f"{r['pnl']/CAP*100:>+5.1f}% {r['n']:>4} {r['wr']:>3.0f}% {r['dd']:>4.1f}% {pf:>5} {r['mcl']:>3}")

    # WORST 10
    print(f"\n  💀 PEORES 10:")
    for r in all_combos[-10:]:
        print(f"     🔴 {r['symbol']:<10} {r['strategy']:<18} ${r['pnl']:>+6.1f} ({r['pnl']/CAP*100:>+.1f}%) DD{r['dd']:.1f}%")

    # STRATEGY RANKING
    print(f"\n{'='*100}")
    print(f"📊 RANKING POR ESTRATEGIA (promedio de 12 monedas)")
    print(f"{'='*100}")
    strat_stats={}
    for r in all_combos:
        s=r['strategy']
        if s not in strat_stats:strat_stats[s]=[]
        strat_stats[s].append(r)
    
    strat_rank=[]
    for s,rl in strat_stats.items():
        avg=np.mean([r['pnl'] for r in rl])
        med=np.median([r['pnl'] for r in rl])
        pos=sum(1 for r in rl if r['pnl']>0)
        best=max(r['pnl'] for r in rl)
        worst=min(r['pnl'] for r in rl)
        avg_dd=np.mean([r['dd'] for r in rl])
        strat_rank.append({'name':s,'avg':avg,'med':med,'pos':pos,'tot':len(rl),
                          'best':best,'worst':worst,'avg_dd':avg_dd})
    
    strat_rank.sort(key=lambda x:-x['avg'])
    print(f"  {'Estrategia':<18} {'Avg$':>7} {'Med$':>7} {'Best':>7} {'Worst':>7} {'Pos':>5} {'AvgDD':>6}")
    print("  "+"-"*60)
    for s in strat_rank:
        e="🟢" if s['avg']>0 else "🔴"
        print(f"  {e} {s['name']:<18} ${s['avg']:>+5.1f} ${s['med']:>+5.1f} ${s['best']:>+5.1f} "
              f"${s['worst']:>+5.1f} {s['pos']:>2}/{s['tot']} {s['avg_dd']:>5.1f}%")

    # COIN RANKING
    print(f"\n{'='*100}")
    print(f"📊 RANKING POR MONEDA (promedio de 20 estrategias)")
    print(f"{'='*100}")
    coin_stats={}
    for r in all_combos:
        s=r['symbol']
        if s not in coin_stats:coin_stats[s]=[]
        coin_stats[s].append(r)
    
    coin_rank=[]
    for s,rl in coin_stats.items():
        avg=np.mean([r['pnl'] for r in rl])
        pos=sum(1 for r in rl if r['pnl']>0)
        best_r=max(rl,key=lambda x:x['pnl'])
        coin_rank.append({'sym':s,'avg':avg,'pos':pos,'tot':len(rl),
                         'best_pnl':best_r['pnl'],'best_strat':best_r['strategy']})
    
    coin_rank.sort(key=lambda x:-x['avg'])
    for c in coin_rank:
        e="🟢" if c['avg']>0 else "🔴"
        print(f"  {e} {c['sym']:<12} Avg ${c['avg']:>+5.1f} | {c['pos']:>2}/{c['tot']} positivas | "
              f"Best: {c['best_strat']} ${c['best_pnl']:>+.1f}")

    # PORTFOLIO
    print(f"\n{'='*100}")
    print(f"💼 PORTFOLIO ÓPTIMO — $100 en las 5 mejores (67 días ciegos)")
    print(f"{'='*100}")
    selected=[];seen=set()
    for r in all_combos:
        if r['symbol'] not in seen and r['pnl']>0:
            selected.append(r);seen.add(r['symbol'])
        if len(selected)==5:break
    if selected:
        per=100/len(selected);total=sum(r['pnl']*(per/100) for r in selected)
        for r in selected:
            sc=r['pnl']*(per/100)
            lv=f" ({r['leverage']}x)" if r['leverage']>1 else ""
            print(f"  🟢 ${per:.0f} → {r['symbol']:<10} ({r['strategy']}{lv}) → ${sc:>+.2f}")
        daily=total/67
        print(f"\n  💰 $100 → ${100+total:.2f} ({total:>+.2f}, {total/100*100:.1f}%) en ~67 días")
        print(f"  📅 Por día: ${daily:.2f}/día")
        print(f"  📅 Mensual estimado: ${daily*30:.1f} ({daily*30/100*100:.1f}%)")
        print(f"  📅 Anual estimado: ${daily*365:.0f} ({daily*365/100*100:.0f}%)")

    total_combos=len(all_combos)
    pos_combos=sum(1 for r in all_combos if r['pnl']>0)
    print(f"\n  📊 {total_combos} combinaciones | {pos_combos} positivas ({pos_combos/total_combos*100:.0f}%)")

if __name__=="__main__":
    asyncio.run(main())
