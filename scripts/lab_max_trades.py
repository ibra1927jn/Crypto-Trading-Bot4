"""
🔥 LAB MODO BESTIA: Máximas operaciones posibles
=================================================
Objetivo: exprimir cada movimiento del mercado.
5 monedas × estrategias ultra-agresivas con targets cortos.
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time

def p(msg): print(msg); sys.stdout.flush()

def bt(data, entry_fn, exit_fn, sl_pct, tp_pct, cap=30.0, pos_pct=90, label=""):
    """Backtest genérico con funciones de entrada/salida."""
    pos=None; bal=cap; trades=[]; peak=cap; maxdd=0
    for i in range(50, len(data)):
        r,prev,price = data.iloc[i],data.iloc[i-1],data.iloc[i]['close']
        if pos is None:
            if entry_fn(r, prev, data, i):
                amt=(bal*pos_pct/100)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl_pct/100),'tp':price*(1+tp_pct/100),'i':i}
        else:
            forced_exit = exit_fn(r, prev, data, i) if exit_fn else False
            if price<=pos['sl'] or price>=pos['tp'] or forced_exit:
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                peak=max(peak,bal); maxdd=max(maxdd,(peak-bal)/peak*100 if peak>0 else 0)
                trades.append({'pnl':pnl,'pct':(price/pos['e']-1)*100,
                    'r':'SL' if price<=pos['sl'] else ('TP' if price>=pos['tp'] else 'EXIT'),
                    'dur':i-pos['i']})
                pos=None
    if pos:
        pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl
        trades.append({'pnl':pnl,'pct':0,'r':'END','dur':0})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    sl_count=len([t for t in trades if t['r']=='SL'])
    tp_count=len([t for t in trades if t['r']=='TP'])
    avg_win=sum(t['pnl'] for t in trades if t['pnl']>0)/max(w,1)
    avg_loss=sum(t['pnl'] for t in trades if t['pnl']<=0)/max(n-w,1)
    return {'label':label,'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100,
            'dd':maxdd,'sl':sl_count,'tp':tp_count,'avg_w':avg_win,'avg_l':avg_loss,
            'avg_dur':sum(t['dur'] for t in trades)/max(n,1)}

def main():
    p("="*80)
    p("🔥 LAB MODO BESTIA: MÁXIMAS OPERACIONES POSIBLES")
    p("📊 5 monedas | Datos 1h (30 días) | Targets ultra-cortos")
    p("="*80)
    
    ex = ccxt.binance({'timeout':30000,'enableRateLimit':True})
    coins = ['XRP/USDT','DOGE/USDT','AVAX/USDT','SHIB/USDT','SOL/USDT']
    
    all_best = {}
    
    for coin in coins:
        p(f"\n{'─'*80}")
        p(f"📊 {coin}")
        p(f"{'─'*80}")
        
        try:
            ohlcv = ex.fetch_ohlcv(coin, '1h', limit=720)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='last')]
            
            # Todos los indicadores
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['RSI_7'] = ta.rsi(df['close'], length=7)  # RSI rápido
            e5=ta.ema(df['close'],5); e9=ta.ema(df['close'],9)
            e13=ta.ema(df['close'],13); e21=ta.ema(df['close'],21)
            if e5 is not None: df['E5']=e5
            if e9 is not None: df['E9']=e9
            if e13 is not None: df['E13']=e13
            if e21 is not None: df['E21']=e21
            df['VOL_SMA'] = df['volume'].rolling(20).mean()
            bb = ta.bbands(df['close'], length=20, std=2.0)
            if bb is not None:
                bbl=[c for c in bb.columns if c.startswith('BBL_')]
                bbu=[c for c in bb.columns if c.startswith('BBU_')]
                bbm=[c for c in bb.columns if c.startswith('BBM_')]
                if bbl: df['BBL']=bb[bbl[0]]
                if bbu: df['BBU']=bb[bbu[0]]
                if bbm: df['BBM']=bb[bbm[0]]
            stoch = ta.stoch(df['high'],df['low'],df['close'])
            if stoch is not None:
                sk=[c for c in stoch.columns if 'STOCHk' in c]
                sd=[c for c in stoch.columns if 'STOCHd' in c]
                if sk: df['STOCH_K']=stoch[sk[0]]
                if sd: df['STOCH_D']=stoch[sd[0]]
            macd_df = ta.macd(df['close'])
            if macd_df is not None:
                mc=[c for c in macd_df.columns if c.startswith('MACD_')]
                ms=[c for c in macd_df.columns if c.startswith('MACDs_')]
                if mc: df['MACD']=macd_df[mc[0]]
                if ms: df['MACD_S']=macd_df[ms[0]]
            
            price_now=df.iloc[-1]['close']; price_start=df.iloc[0]['close']
            bh=(price_now/price_start-1)*100
            p(f"   {len(df)} velas | ${price_start:.4f} → ${price_now:.4f} (B&H: {bh:+.1f}%)")
            
            # ─── ESTRATEGIAS ULTRA-AGRESIVAS ───
            strategies = []
            
            # 1. Scalp RSI<40 (SL-1.5% / TP+2%) — máxima frecuencia
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: not pd.isna(r.get('RSI',50)) and not pd.isna(p.get('RSI',50)) and p['RSI']<40 and r['RSI']>p['RSI'],
                exit_fn=lambda r,p,d,i: not pd.isna(r.get('RSI',50)) and r['RSI']>60,
                sl_pct=1.5, tp_pct=2, label='Scalp RSI<40 (SL1.5/TP2)'))
            
            # 2. Scalp RSI<45 (SL-1% / TP+1.5%) — máximísima frecuencia
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: not pd.isna(r.get('RSI',50)) and not pd.isna(p.get('RSI',50)) and p['RSI']<45 and r['RSI']>p['RSI'],
                exit_fn=lambda r,p,d,i: not pd.isna(r.get('RSI',50)) and r['RSI']>55,
                sl_pct=1.0, tp_pct=1.5, label='MicroScalp RSI<45 (SL1/TP1.5)'))
            
            # 3. EMA 5/13 Cross (SL-2% / TP+3%) — sigue micro-tendencias
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: all(not pd.isna(x) for x in [r.get('E5'),r.get('E13'),p.get('E5'),p.get('E13')]) and p['E5']<=p['E13'] and r['E5']>r['E13'],
                exit_fn=lambda r,p,d,i: all(not pd.isna(x) for x in [r.get('E5'),r.get('E13')]) and r['E5']<r['E13'],
                sl_pct=2, tp_pct=3, label='EMA 5/13 Cross (SL2/TP3)'))
            
            # 4. BB Bounce ultra-tight (SL-1.5% / TP+2.5%)
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: not pd.isna(r.get('BBL',0)) and r['close']<=r.get('BBL',0)*1.005,
                exit_fn=lambda r,p,d,i: not pd.isna(r.get('BBM',0)) and r['close']>=r.get('BBM',0),
                sl_pct=1.5, tp_pct=2.5, label='BB Bounce→Mid (SL1.5/TP2.5)'))
            
            # 5. Stochastic oversold (SL-2% / TP+3%)
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: not pd.isna(r.get('STOCH_K',50)) and not pd.isna(p.get('STOCH_K',50)) and p['STOCH_K']<20 and r['STOCH_K']>p['STOCH_K'],
                exit_fn=lambda r,p,d,i: not pd.isna(r.get('STOCH_K',50)) and r['STOCH_K']>80,
                sl_pct=2, tp_pct=3, label='Stoch<20→80 (SL2/TP3)'))
            
            # 6. MACD Cross (SL-2% / TP+3%)
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: all(not pd.isna(x) for x in [r.get('MACD'),r.get('MACD_S'),p.get('MACD'),p.get('MACD_S')]) and p['MACD']<=p['MACD_S'] and r['MACD']>r['MACD_S'],
                exit_fn=lambda r,p,d,i: all(not pd.isna(x) for x in [r.get('MACD'),r.get('MACD_S')]) and r['MACD']<r['MACD_S'],
                sl_pct=2, tp_pct=3, label='MACD Cross (SL2/TP3)'))
            
            # 7. RSI7<30 rápido (SL-2% / TP+3%) — RSI ultracorto
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: not pd.isna(r.get('RSI_7',50)) and not pd.isna(p.get('RSI_7',50)) and p['RSI_7']<30 and r['RSI_7']>p['RSI_7'],
                exit_fn=lambda r,p,d,i: not pd.isna(r.get('RSI_7',50)) and r['RSI_7']>70,
                sl_pct=2, tp_pct=3, label='RSI7<30 Rápido (SL2/TP3)'))
            
            # 8. Combo: RSI<35 + por encima EMA5 (SL-2% / TP+4%)
            strategies.append(bt(df,
                entry_fn=lambda r,p,d,i: not pd.isna(r.get('RSI',50)) and not pd.isna(r.get('E5',0)) and r['RSI']<35 and r['close']>r.get('E5',0),
                exit_fn=lambda r,p,d,i: not pd.isna(r.get('RSI',50)) and r['RSI']>65,
                sl_pct=2, tp_pct=4, label='RSI<35+>EMA5 (SL2/TP4)'))
            
            # Print results sorted by trades (most first)
            strategies.sort(key=lambda x: x['trades'], reverse=True)
            
            p(f"\n   {'Estrategia':<32s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | {'DD':>5s} | {'AvgW':>5s} | {'AvgL':>6s} | {'SL':>2s}|{'TP':>2s} | Dur")
            p(f"   {'-'*32}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-{'-'*5}-+-{'-'*5}-+-{'-'*6}-+-{'-'*2}+{'-'*2}-+----")
            
            for s in strategies:
                e = '🟢' if s['pnl']>0 else ('⚪' if s['trades']==0 else '🔴')
                dur_h = s['avg_dur']
                p(f"   {s['label']:<32s} | {e}${s['pnl']:+5.2f} | {s['trades']:3d} | {s['wr']:3.0f}% | {s['dd']:4.1f}% | ${s['avg_w']:.2f} | ${s['avg_l']:.2f} | {s['sl']:2d}|{s['tp']:2d} | {dur_h:.0f}h")
            
            # Best by PnL (only if has trades)
            with_trades = [s for s in strategies if s['trades']>0]
            if with_trades:
                best_pnl = max(with_trades, key=lambda x: x['pnl'])
                most_trades = max(with_trades, key=lambda x: x['trades'])
                p(f"\n   🏆 MÁS RENTABLE: {best_pnl['label']} → ${best_pnl['pnl']:+.2f} ({best_pnl['trades']} trades)")
                p(f"   🔥 MÁS TRADES:   {most_trades['label']} → {most_trades['trades']} trades (${most_trades['pnl']:+.2f})")
                all_best[coin] = {'best_pnl': best_pnl, 'most_trades': most_trades, 'bh': bh}
        
        except Exception as e:
            p(f"   ❌ Error: {e}")
        
        time.sleep(1)
    
    # ═══ RESUMEN ═══
    p(f"\n{'='*80}")
    p("🏆 RESUMEN: MÁXIMAS OPERACIONES")
    p(f"{'='*80}")
    
    total_pnl_best = 0
    total_pnl_most = 0
    total_trades_most = 0
    
    p(f"\n   {'Moneda':<12s} | {'Más rentable':<32s} | {'PnL':>6s} | {'Más trades':<32s} | {'#':>3s} | {'PnL':>6s}")
    p(f"   {'-'*12}-+-{'-'*32}-+-{'-'*6}-+-{'-'*32}-+-{'-'*3}-+-{'-'*6}")
    
    for coin, d in all_best.items():
        bp = d['best_pnl']; mt = d['most_trades']
        total_pnl_best += bp['pnl']
        total_pnl_most += mt['pnl']
        total_trades_most += mt['trades']
        e1='🟢' if bp['pnl']>0 else '🔴'
        e2='🟢' if mt['pnl']>0 else '🔴'
        p(f"   {coin:<12s} | {bp['label']:<32s} | {e1}${bp['pnl']:+.2f} | {mt['label']:<32s} | {mt['trades']:3d} | {e2}${mt['pnl']:+.2f}")
    
    p(f"\n   TOTAL (más rentable): ${total_pnl_best:+.2f} ({total_pnl_best/150*100:+.1f}%)")
    p(f"   TOTAL (más trades):  ${total_pnl_most:+.2f} | {total_trades_most} trades ({total_pnl_most/150*100:+.1f}%)")

if __name__ == '__main__':
    main()
