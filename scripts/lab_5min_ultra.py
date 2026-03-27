"""
⚡ LAB ULTRA-AGRESIVO: Velas 5min, estrategias combinadas
==========================================================
Timeframe 5min = 12x más señales que 1h
+ Combinar las mejores estrategias de los labs anteriores
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time

def p(msg): print(msg); sys.stdout.flush()

def safe(row, col, default=50):
    v = row.get(col, None)
    return float(v) if v is not None and not pd.isna(v) else default

def run_combined(df, cap=30.0):
    """
    Combo: ejecuta TODAS las estrategias en paralelo.
    Si cualquiera da BUY → compra. Primera en dar EXIT → vende.
    Simula tener todas las estrategias activas a la vez.
    """
    pos=None; bal=cap; trades=[]
    
    for i in range(60, len(data)):
        r=data.iloc[i]; p1=data.iloc[i-1]; p2=data.iloc[i-2]
        price=r['close']
        
        if pos is None:
            signal = check_any_entry(r, p1, p2)
            if signal:
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-signal['sl']/100),
                     'tp':price*(1+signal['tp']/100),'i':i,'strat':signal['name']}
        else:
            if price<=pos['sl'] or price>=pos['tp'] or check_exit(r, p1):
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'strat':pos['strat'],
                    'r':'SL' if price<=pos['sl'] else ('TP' if price>=pos['tp'] else 'EXIT')})
                pos=None
    
    if pos:
        pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl
        trades.append({'pnl':pnl,'strat':'END','r':'END'})
    
    return bal-cap, trades

def bt(data, entry_fn, exit_fn, sl, tp, cap=30.0, label=""):
    pos=None; bal=cap; trades=[]
    for i in range(60, len(data)):
        r=data.iloc[i]; p1=data.iloc[i-1]; p2=data.iloc[i-2]; price=r['close']
        if pos is None:
            if entry_fn(r,p1,p2,data,i):
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl/100),'tp':price*(1+tp/100),'i':i}
        else:
            forced=exit_fn(r,p1,data,i) if exit_fn else False
            if price<=pos['sl'] or price>=pos['tp'] or forced:
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else ('TP' if price>=pos['tp'] else 'EXIT')})
                pos=None
    if pos:
        pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl
        trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    return {'label':label,'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100}

def main():
    p("="*80)
    p("⚡ LAB ULTRA-AGRESIVO: VELAS 5min + ESTRATEGIAS COMBINADAS")
    p("   1000 velas de 5min ≈ 3.5 días | Alta frecuencia")
    p("   Proyección a 30 días al final")
    p("="*80)
    
    ex = ccxt.binance({'timeout':30000,'enableRateLimit':True})
    coins = ['XRP/USDT','DOGE/USDT','AVAX/USDT','SHIB/USDT','SOL/USDT']
    all_results = {}
    
    for coin in coins:
        p(f"\n{'─'*80}")
        p(f"📊 {coin} (5min)")
        p(f"{'─'*80}")
        
        try:
            ohlcv = ex.fetch_ohlcv(coin, '5m', limit=1000)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='last')]
            
            # Todos los indicadores
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['RSI_7'] = ta.rsi(df['close'], length=7)
            for l in [5,9,13,21,50]:
                e=ta.ema(df['close'],l)
                if e is not None: df[f'E{l}']=e
            df['VOL_SMA'] = df['volume'].rolling(20).mean()
            df['VOL_R'] = df['volume'] / df['VOL_SMA'].replace(0,1)
            bb=ta.bbands(df['close'],20,2.0)
            if bb is not None:
                for px,nm in [('BBL_','BBL'),('BBU_','BBU'),('BBM_','BBM')]:
                    cc=[c for c in bb.columns if c.startswith(px)]
                    if cc: df[nm]=bb[cc[0]]
            st=ta.stoch(df['high'],df['low'],df['close'])
            if st is not None:
                for px,nm in [('STOCHk','SK'),('STOCHd','SD')]:
                    cc=[c for c in st.columns if px in c]
                    if cc: df[nm]=st[cc[0]]
            mc=ta.macd(df['close'])
            if mc is not None:
                for px,nm in [('MACD_','MACD'),('MACDs_','MACD_S')]:
                    cc=[c for c in mc.columns if c.startswith(px)]
                    if cc: df[nm]=mc[cc[0]]
            adx_df=ta.adx(df['high'],df['low'],df['close'],14)
            if adx_df is not None:
                ac=[c for c in adx_df.columns if c.startswith('ADX_')]
                if ac: df['ADX']=adx_df[ac[0]]
            df['BULL'] = df['close'] > df['open']
            df['BEAR'] = df['close'] < df['open']
            
            price_now=df.iloc[-1]['close']; price_start=df.iloc[0]['close']
            bh=(price_now/price_start-1)*100
            days = (df.index[-1] - df.index[0]).total_seconds() / 86400
            p(f"   {len(df)} velas | {days:.1f} días | ${price_start:.4f} → ${price_now:.4f} (B&H: {bh:+.1f}%)")
            
            strategies = []
            
            # 1. RSI<30 Agresivo (Ganadora lab 1)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'RSI')<30 and safe(r,'RSI')>safe(p,'RSI'),
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>65,
                sl=3, tp=5, label='RSI<30 Agresivo'))
            
            # 2. RSI<35 + Volumen (calidad media, frecuencia alta)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'RSI')<35 and safe(r,'RSI')>safe(p,'RSI') and safe(r,'VOL_R',1)>1.2,
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>65,
                sl=2.5, tp=4, label='RSI<35+Vol'))
            
            # 3. Momentum Confirmado (Ganadora francotirador)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'RSI')<42 and safe(r,'RSI')>42 and safe(r,'MACD',0)>safe(r,'MACD_S',0) and safe(r,'VOL_R',1)>1.3,
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>70 or safe(r,'MACD',0)<safe(r,'MACD_S',0),
                sl=2, tp=3, label='Momentum Confirmado'))
            
            # 4. Triple Dip (Ganadora francotirador DOGE)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(r,'RSI')<35 and safe(r,'RSI')>safe(p,'RSI') and safe(r,'SK',50)<25 and r['close']<safe(r,'BBM',r['close']*2),
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>65 or safe(r,'SK',50)>80,
                sl=3, tp=5, label='Triple Dip'))
            
            # 5. Scalp RSI<40 (Ganadora max-trades XRP/SHIB)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'RSI')<40 and safe(r,'RSI')>safe(p,'RSI'),
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>60,
                sl=1.5, tp=2, label='Scalp RSI<40'))
            
            # 6. EMA5/13 + RSI (Combinación nuevas)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'E5',0)<=safe(p,'E13',0) and safe(r,'E5',0)>safe(r,'E13',0) and safe(r,'RSI')<55,
                exit_fn=lambda r,p,d,i: safe(r,'E5',0)<safe(r,'E13',0) or safe(r,'RSI')>70,
                sl=2, tp=3, label='EMA5/13 Cross+RSI'))
            
            # 7. Doble Bounce + Vol (Mejorada)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: p2.get('BEAR',False) and p.get('BEAR',False) and r.get('BULL',False) and safe(r,'RSI')<40 and safe(r,'VOL_R',1)>1.0,
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>60,
                sl=2, tp=3.5, label='Doble Bounce+Vol'))
            
            # 8. RSI7<25 Rápido (ultra-agresivo con RSI corto)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'RSI_7')<25 and safe(r,'RSI_7')>safe(p,'RSI_7'),
                exit_fn=lambda r,p,d,i: safe(r,'RSI_7')>65,
                sl=2, tp=3, label='RSI7<25 Ultra'))
            
            # 9. MACD Cross + ADX>20 (tendencia confirmada)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: safe(p,'MACD',0)<=safe(p,'MACD_S',0) and safe(r,'MACD',0)>safe(r,'MACD_S',0) and safe(r,'ADX',0)>20,
                exit_fn=lambda r,p,d,i: safe(r,'MACD',0)<safe(r,'MACD_S',0),
                sl=2, tp=3, label='MACD+ADX>20'))
            
            # 10. COMBO: OR de las 3 mejores (más trades posible con filtro)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    (safe(p,'RSI')<30 and safe(r,'RSI')>safe(p,'RSI')) or  # RSI dip
                    (safe(p,'RSI')<42 and safe(r,'RSI')>42 and safe(r,'MACD',0)>safe(r,'MACD_S',0)) or  # Momentum
                    (p.get('BEAR',False) and r.get('BULL',False) and safe(r,'RSI')<40 and safe(r,'VOL_R',1)>1.2)  # Bounce
                ),
                exit_fn=lambda r,p,d,i: safe(r,'RSI')>65,
                sl=2.5, tp=4, label='⚡COMBO (RSI+Mom+Bounce)'))
            
            # Sort by PnL
            strategies.sort(key=lambda x: x['pnl'], reverse=True)
            
            p(f"\n   {'Estrategia':<32s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | {'→30d PnL':>9s} | {'→30d #':>6s}")
            p(f"   {'-'*32}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-{'-'*9}-+-{'-'*6}")
            
            multiplier = 30 / max(days, 0.5)  # Proyección a 30 días
            
            for s in strategies:
                e = '🟢' if s['pnl']>0 else ('⚪' if s['trades']==0 else '🔴')
                proj_pnl = s['pnl'] * multiplier
                proj_trades = int(s['trades'] * multiplier)
                p(f"   {s['label']:<32s} | {e}${s['pnl']:+5.2f} | {s['trades']:3d} | {s['wr']:3.0f}% | ${proj_pnl:+7.2f} | {proj_trades:6d}")
            
            with_trades = [s for s in strategies if s['trades']>=2]
            if with_trades:
                best = max(with_trades, key=lambda x: x['pnl'])
                proj = best['pnl'] * multiplier
                p(f"\n   🏆 MEJOR: {best['label']} → ${best['pnl']:+.2f} en {days:.1f}d → ${proj:+.2f}/mes proyectado")
                all_results[coin] = {'best': best, 'bh': bh, 'days': days, 'mult': multiplier}
            
        except Exception as e:
            p(f"   ❌ Error: {e}")
        time.sleep(1)
    
    # ═══ RESUMEN ═══
    p(f"\n{'='*80}")
    p("🏆 RESUMEN — PROYECCIÓN A 30 DÍAS")
    p(f"{'='*80}")
    
    total_proj = 0; total_trades_proj = 0
    p(f"\n   {'Moneda':<12s} | {'Estrategia':<32s} | {'Real':>6s} | {'→30d':>7s} | {'#/mes':>5s} | {'WR':>4s}")
    p(f"   {'-'*12}-+-{'-'*32}-+-{'-'*6}-+-{'-'*7}-+-{'-'*5}-+-{'-'*4}")
    
    for coin, d in all_results.items():
        b=d['best']; m=d['mult']
        proj=b['pnl']*m; proj_t=int(b['trades']*m)
        total_proj+=proj; total_trades_proj+=proj_t
        e='🟢' if proj>0 else '🔴'
        p(f"   {coin:<12s} | {b['label']:<32s} | ${b['pnl']:+.2f} | {e}${proj:+5.0f} | {proj_t:5d} | {b['wr']:3.0f}%")
    
    p(f"\n   TOTAL PROYECTADO (30d): ${total_proj:+.2f} ({total_proj/150*100:+.1f}%) | {total_trades_proj} trades")
    p(f"   Si escalas a $1,000:    ${total_proj/150*1000:+.0f}/mes")
    p(f"   Si escalas a $5,000:    ${total_proj/150*5000:+.0f}/mes")

if __name__ == '__main__':
    main()
