"""
CT4 LAB — DATOS REALES: 6 meses de Binance Mainnet
=====================================================
POR FIN datos REALES. No testnet simulado.

Datos: Sep 1 2025 → Mar 5 2026 (~6 meses, ~185 días)
Split: 50% train (3 meses) | 50% CIEGO (3 meses)
API: Binance MAINNET pública (no necesita auth)

Top 10 estrategias × 8 monedas top.
$100 capital, Jupiter fees (0.05%).
"""
import asyncio,sys,os
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime,timezone

CAP=100; FEE=0.0005; POS80=0.80; POS95=0.95

# Top coins from all labs (excluding ETH, SOL, DOGE, XRP that lost)
COINS=['BTC/USDT','APT/USDT','NEAR/USDT','FIL/USDT','TIA/USDT',
       'SAND/USDT','LINK/USDT','FET/USDT','SOL/USDT','ETH/USDT',
       'DOGE/USDT','BONK/USDT']

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
    df['MOM3']=(c-c.shift(3))/c.shift(3)*100
    df['E50H']=c.ewm(span=600).mean()
    return df

def v(r,c,d=0):
    x=r.get(c,d);return d if pd.isna(x) else x

def bt(df,buy,ext,sl,tp,pos_pct,trail=None,leverage=1):
    cap=CAP;pk=CAP;dd=0;pos=None;trades=[];equity_curve=[]
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
        equity_curve.append(cap)
    if pos:
        p=df.iloc[-1]['close'];pnl=(p-pos['e'])*pos['sz']
        pnl-=pos['f']+abs(p*pos['sz']*FEE);cap+=pnl;trades.append(pnl)
    w=[t for t in trades if t>0];lo=[t for t in trades if t<=0]
    gl=sum(lo) if lo else 0
    mcl=0;cl=0
    for t in trades:
        if t<=0:cl+=1;mcl=max(mcl,cl)
        else:cl=0
    return{'n':len(trades),'w':len(w),'wr':len(w)/len(trades)*100 if trades else 0,
           'pnl':sum(trades),'dd':dd,'pf':sum(w)/abs(gl) if gl!=0 else 999,
           'cap':cap,'mcl':mcl}

# EXITS
def x1(r,p):return v(p,'E5')>=v(p,'E13') and v(r,'E5')<v(r,'E13')
def x2(r,p):return v(r,'BP')>0.90
def x3(r,p):return v(r,'RSI')>70
def x4(r,p):return v(r,'BP')>0.95 or x1(r,p)
def x0(r,p):return False

# TOP 10 STRATEGIES
S=[
("2x BB+Vol",
 lambda r,p,q:v(r,'BP',0.5)<0.10 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x2, -2, 5, POS80, 1.5, 2),

("RSI Extreme",
 lambda r,p,q:v(p,'RSI',50)<20 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x3, -3, 6, POS80, 2.0, 1),

("BB Agresivo",
 lambda r,p,q:v(r,'BP',0.5)<0.05 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x2, -3, 6, POS80, 2.0, 1),

("Combo Killer",
 lambda r,p,q:v(r,'BP',0.5)<0.20 and v(r,'VR',1)>1.5 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>r['open'] and r['close']>v(r,'E50')*0.98,
 x2, -2, 5, POS80, 1.5, 1),

("Breakout",
 lambda r,p,q:r['close']>v(p,'H10') and v(r,'VR',1)>1.5 and v(r,'ADX')>20,
 x1, -3, 8, POS80, None, 1),

("VolBreak",
 lambda r,p,q:v(r,'VR',1)>2.0 and r['close']>v(p,'H5') and v(r,'ADX')>20 and r['close']>v(r,'E21'),
 x1, -2, 6, POS80, 2.0, 1),

("DoubleBot",
 lambda r,p,q:v(r,'BP',0.5)<0.10 and v(p,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.96,
 x2, -4, 8, POS80, 2.0, 1),

("RSI+BB",
 lambda r,p,q:v(r,'RSI',50)<30 and v(r,'BP',0.5)<0.15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.97,
 x4, -3, 6, POS80, 2.0, 1),

("AllIn RSI<15",
 lambda r,p,q:v(p,'RSI',50)<15 and v(r,'RSI',50)>v(p,'RSI',50) and r['close']>v(r,'E50')*0.95,
 x3, -4, 8, POS95, 2.0, 1),

("MomBurst+",
 lambda r,p,q:v(r,'CP')>0.8 and v(r,'VR',1)>2.5 and r['close']>v(r,'E9'),
 x1, -2, 4, POS95, 1.0, 1),
]

async def dl(exchange,sym,start_date):
    """Download REAL data from Binance MAINNET."""
    a=[]
    since=int(start_date.timestamp()*1000)
    end=int(datetime(2026,3,5,9,0,tzinfo=timezone.utc).timestamp()*1000)
    retries = 0
    try:
        while since<end:
            try:
                c=await exchange.fetch_ohlcv(sym,'5m',since=since,limit=1000)
            except Exception as e:
                retries += 1
                if retries > 5: break
                await asyncio.sleep(2)
                continue
            if not c:break
            a.extend(c);since=c[-1][0]+1;await asyncio.sleep(0.15)
    except:pass
    if len(a)<1000:return None
    seen=set();u=[]
    for c in a:
        if c[0] not in seen:seen.add(c[0]);u.append(c)
    u.sort(key=lambda x:x[0])
    df=pd.DataFrame(u,columns=['timestamp','open','high','low','close','volume'])
    df['timestamp']=pd.to_datetime(df['timestamp'],unit='ms')
    df.set_index('timestamp',inplace=True)
    return calc(df)

async def main():
    start_date=datetime(2025,9,1,0,0,tzinfo=timezone.utc)
    print("="*100)
    print(f"🔴 CT4 LAB — DATOS REALES DE BINANCE MAINNET")
    print(f"   Sep 1 2025 → Mar 5 2026 (~6 meses, ~185 días)")
    print(f"   Split: 50% train | 50% CIEGO (3 MESES)")
    print(f"   Top 10 estrategias × {len(COINS)} monedas")
    print(f"   ⚠️ ESTOS SON PRECIOS REALES, NO SIMULADOS")
    print("="*100)

    # Binance MAINNET — public API, no auth needed for OHLCV
    exchange=ccxt.binance({'sandbox': False, 'enableRateLimit': True})
    
    data={}
    for sym in COINS:
        print(f"  📡 {sym:<13}",end="",flush=True)
        df=await dl(exchange,sym,start_date)
        if df is not None and len(df)>1000:
            days=len(df)*5/60/24
            p_start=df.iloc[250]['close']
            p_end=df.iloc[-1]['close']
            ret=(p_end-p_start)/p_start*100
            data[sym]=df
            print(f"✅ {len(df):>6} velas ({days:.0f} días) | ${p_start:.2f} → ${p_end:.2f} | B&H {ret:>+.1f}%")
        else:
            print(f"❌ Insuficiente ({len(df) if df is not None else 0} velas)")
    
    await exchange.close()
    print(f"\n  📊 {len(data)} monedas con datos reales")

    if not data:
        print("❌ No se pudieron descargar datos. Puede ser un problema de red.")
        return

    # ═══ IN-SAMPLE + OOS ═══
    all_in=[]
    all_oos=[]
    
    for sym,df in data.items():
        cut=int(len(df)*0.50)  # 50/50 split
        df_in=calc(df.iloc[:cut].copy())
        df_oos=calc(df.iloc[max(0,cut-250):].copy())  # Keep 250 bars for warmup
        
        in_days=len(df_in)*5/60/24
        oos_days=(len(df)-cut)*5/60/24
        bh_oos=(df.iloc[-1]['close']-df.iloc[cut]['close'])/df.iloc[cut]['close']*100
        
        print(f"\n{'='*100}")
        print(f"📊 {sym} — DATOS REALES | OOS: {oos_days:.0f} días | B&H OOS: {bh_oos:>+.1f}%")
        print(f"{'='*100}")
        
        # IN-SAMPLE
        print(f"\n  IN-SAMPLE ({in_days:.0f} días):")
        print(f"  {'Estrategia':<18} {'L':>2} {'PnL':>8} {'T':>4} {'WR':>4} {'DD%':>5} {'PF':>5}")
        print("  "+"-"*50)
        for name,buy,ext,sl,tp,pos,trail,lev in S:
            r=bt(df_in,buy,ext,sl,tp,pos,trail,lev)
            r['symbol']=sym;r['strategy']=name;r['leverage']=lev
            all_in.append(r)
            e="🟢" if r['pnl']>0 else "🔴"
            pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
            lv=f"{lev}x" if lev>1 else "  "
            print(f"  {e} {name:<18} {lv:>2} ${r['pnl']:>+6.1f} {r['n']:>4} {r['wr']:>3.0f}% {r['dd']:>4.1f}% {pf:>5}")
        
        # OOS
        print(f"\n  OUT-OF-SAMPLE CIEGO ({oos_days:.0f} días):")
        print(f"  {'Estrategia':<18} {'L':>2} {'PnL':>8} {'T':>4} {'WR':>4} {'DD%':>5} {'PF':>5} {'MCL':>3}")
        print("  "+"-"*55)
        for name,buy,ext,sl,tp,pos,trail,lev in S:
            r=bt(df_oos,buy,ext,sl,tp,pos,trail,lev)
            r['symbol']=sym;r['strategy']=name;r['leverage']=lev
            all_oos.append(r)
            e="🟢" if r['pnl']>0 else "🔴"
            pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
            lv=f"{lev}x" if lev>1 else "  "
            print(f"  {e} {name:<18} {lv:>2} ${r['pnl']:>+6.1f} {r['n']:>4} {r['wr']:>3.0f}% {r['dd']:>4.1f}% {pf:>5} {r['mcl']:>3}")

    # ═══ WALK-FORWARD VALIDATION ═══
    print(f"\n{'='*100}")
    print(f"⚖️  WALK-FORWARD — ¿Quién SOBREVIVE con datos reales?")
    print(f"{'='*100}")
    for name in [s[0] for s in S]:
        in_avg=np.mean([r['pnl'] for r in all_in if r['strategy']==name])
        oos_avg=np.mean([r['pnl'] for r in all_oos if r['strategy']==name])
        oos_pos=sum(1 for r in all_oos if r['strategy']==name and r['pnl']>0)
        oos_tot=sum(1 for r in all_oos if r['strategy']==name)
        if in_avg>0 and oos_avg>0: vd="✅ REAL"
        elif oos_avg>0: vd="🔄 SUPERA"
        elif in_avg>0: vd="❌ OVERFIT"
        else: vd="💀 MUERTA"
        print(f"  {name:<18} In: ${in_avg:>+5.1f} → OOS: ${oos_avg:>+5.1f} | {oos_pos}/{oos_tot} monedas | {vd}")

    # ═══ TOP 20 OOS ═══
    all_oos.sort(key=lambda x:-x['pnl'])
    print(f"\n{'='*100}")
    print(f"🏆 TOP 20 — DATOS REALES, TEST CIEGO ~3 MESES")
    print(f"{'='*100}")
    print(f"  {'#':>3} {'Moneda':<12} {'Estrategia':<18} {'L':>2} {'PnL':>8} {'Ret%':>6} {'T':>4} "
          f"{'WR':>4} {'DD%':>5} {'PF':>5} {'MCL':>3}")
    print("  "+"-"*78)
    for i,r in enumerate(all_oos[:20]):
        e="🟢" if r['pnl']>0 else "🔴"
        pf=f"{r['pf']:.1f}" if r['pf']<100 else "∞"
        lv=f"{r['leverage']}x" if r['leverage']>1 else "  "
        print(f"  {i+1:>3} {e} {r['symbol']:<10} {r['strategy']:<18} {lv:>2} ${r['pnl']:>+6.1f} "
              f"{r['pnl']/CAP*100:>+5.1f}% {r['n']:>4} {r['wr']:>3.0f}% {r['dd']:>4.1f}% {pf:>5} {r['mcl']:>3}")

    # WORST 5
    print(f"\n  💀 PEORES 5:")
    for r in all_oos[-5:]:
        print(f"     🔴 {r['symbol']:<10} {r['strategy']:<18} ${r['pnl']:>+6.1f} DD{r['dd']:.1f}%")

    # STRATEGY RANKING
    print(f"\n{'='*100}")
    print(f"📊 RANKING ESTRATEGIA (promedio OOS real)")
    print(f"{'='*100}")
    sr={}
    for r in all_oos:
        s=r['strategy']
        if s not in sr:sr[s]=[]
        sr[s].append(r)
    ranked=[]
    for s,rl in sr.items():
        avg=np.mean([r['pnl'] for r in rl]);pos=sum(1 for r in rl if r['pnl']>0)
        ranked.append((s,avg,pos,len(rl),max(r['pnl'] for r in rl),min(r['pnl'] for r in rl)))
    ranked.sort(key=lambda x:-x[1])
    for s,avg,pos,tot,best,worst in ranked:
        e="🟢" if avg>0 else "🔴"
        print(f"  {e} {s:<18} Avg ${avg:>+5.1f} | {pos}/{tot} monedas ✅ | Best ${best:>+.1f} | Worst ${worst:>+.1f}")

    # COIN RANKING
    print(f"\n{'='*100}")
    print(f"📊 RANKING MONEDA (promedio OOS real)")
    print(f"{'='*100}")
    cr={}
    for r in all_oos:
        s=r['symbol']
        if s not in cr:cr[s]=[]
        cr[s].append(r)
    coin_ranked=[]
    for s,rl in cr.items():
        avg=np.mean([r['pnl'] for r in rl]);pos=sum(1 for r in rl if r['pnl']>0)
        best_r=max(rl,key=lambda x:x['pnl'])
        coin_ranked.append((s,avg,pos,len(rl),best_r))
    coin_ranked.sort(key=lambda x:-x[1])
    for s,avg,pos,tot,best in coin_ranked:
        e="🟢" if avg>0 else "🔴"
        print(f"  {e} {s:<12} Avg ${avg:>+5.1f} | {pos}/{tot} ✅ | Best: {best['strategy']} ${best['pnl']:>+.1f}")

    # PORTFOLIO
    print(f"\n{'='*100}")
    print(f"💼 PORTFOLIO REAL — $100, datos reales, 3 meses ciegos")
    print(f"{'='*100}")
    selected=[];seen=set()
    for r in all_oos:
        if r['symbol'] not in seen and r['pnl']>0:
            selected.append(r);seen.add(r['symbol'])
        if len(selected)==5:break
    if selected:
        per=100/len(selected);total=sum(r['pnl']*(per/100) for r in selected)
        oos_days_avg=90  # ~3 months
        for r in selected:
            sc=r['pnl']*(per/100)
            lv=f" ({r['leverage']}x)" if r['leverage']>1 else ""
            print(f"  🟢 ${per:.0f} → {r['symbol']:<10} ({r['strategy']}{lv}) → ${sc:>+.2f}")
        daily=total/oos_days_avg
        print(f"\n  💰 $100 → ${100+total:.2f} ({total:>+.2f}, {total/100*100:.1f}%) en ~3 meses")
        print(f"  📅 Mensual: ${total/3:.1f} ({total/3:.1f}%)")
        print(f"  📅 Anual: ${daily*365:.0f} ({daily*365:.0f}%)")
    else:
        print("  ❌ Ninguna combinación fue positiva en OOS")
    
    total_combos=len(all_oos)
    pos_combos=sum(1 for r in all_oos if r['pnl']>0)
    print(f"\n  📊 {total_combos} combinaciones | {pos_combos} positivas ({pos_combos/total_combos*100:.0f}%)")

if __name__=="__main__":
    asyncio.run(main())
