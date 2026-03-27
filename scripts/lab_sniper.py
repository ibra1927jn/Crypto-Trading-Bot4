"""
🎯 LAB FRANCOTIRADOR: Pocos trades, alta calidad
=================================================
Filtros anti-ruido: solo entrar cuando 2-3 indicadores confirman.
Objetivo: 3-5 trades/mes por moneda con WR > 60%.
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time

def p(msg): print(msg); sys.stdout.flush()

def bt(data, entry_fn, exit_fn, sl_pct, tp_pct, cap=30.0, label=""):
    pos=None; bal=cap; trades=[]
    for i in range(60, len(data)):
        r = data.iloc[i]; prev = data.iloc[i-1]; prev2 = data.iloc[i-2]
        price = r['close']
        if pos is None:
            if entry_fn(r, prev, prev2, data, i):
                amt=(bal*0.90)/price
                pos={'e':price,'a':amt,'sl':price*(1-sl_pct/100),'tp':price*(1+tp_pct/100),'i':i}
        else:
            forced = exit_fn(r, prev, data, i) if exit_fn else False
            if price<=pos['sl'] or price>=pos['tp'] or forced:
                pnl=(price-pos['e'])*pos['a']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else ('TP' if price>=pos['tp'] else 'EXIT')})
                pos=None
    if pos:
        pnl=(data.iloc[-1]['close']-pos['e'])*pos['a']; bal+=pnl
        trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    sl_n=len([t for t in trades if t['r']=='SL']); tp_n=len([t for t in trades if t['r']=='TP'])
    return {'label':label,'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100,'sl':sl_n,'tp':tp_n}

def safe(row, col, default=50):
    v = row.get(col, None)
    return float(v) if v is not None and not pd.isna(v) else default

def main():
    p("="*80)
    p("🎯 LAB FRANCOTIRADOR: POCOS TRADES, ALTA CALIDAD")
    p("   Filtros anti-ruido: solo entrar con 2-3 confirmaciones")
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
            
            # Indicadores
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['RSI_7'] = ta.rsi(df['close'], length=7)
            for l in [5,9,13,21,50]: 
                e=ta.ema(df['close'],l)
                if e is not None: df[f'E{l}']=e
            df['VOL_SMA'] = df['volume'].rolling(20).mean()
            df['VOL_RATIO'] = df['volume'] / df['VOL_SMA'].replace(0,1)
            bb = ta.bbands(df['close'], length=20, std=2.0)
            if bb is not None:
                for prefix,name in [('BBL_','BBL'),('BBU_','BBU'),('BBM_','BBM')]:
                    cols=[c for c in bb.columns if c.startswith(prefix)]
                    if cols: df[name]=bb[cols[0]]
            stoch = ta.stoch(df['high'],df['low'],df['close'])
            if stoch is not None:
                for prefix,name in [('STOCHk','SK'),('STOCHd','SD')]:
                    cols=[c for c in stoch.columns if prefix in c]
                    if cols: df[name]=stoch[cols[0]]
            atr = ta.atr(df['high'],df['low'],df['close'],length=14)
            if atr is not None: df['ATR']=atr
            adx_df = ta.adx(df['high'],df['low'],df['close'],length=14)
            if adx_df is not None:
                ac=[c for c in adx_df.columns if c.startswith('ADX_')]
                if ac: df['ADX']=adx_df[ac[0]]
            macd_df = ta.macd(df['close'])
            if macd_df is not None:
                mc=[c for c in macd_df.columns if c.startswith('MACD_')]
                ms=[c for c in macd_df.columns if c.startswith('MACDs_')]
                if mc: df['MACD']=macd_df[mc[0]]
                if ms: df['MACD_S']=macd_df[ms[0]]
            # Prev candle color
            df['BULL'] = df['close'] > df['open']
            df['BEAR'] = df['close'] < df['open']
            
            price_now=df.iloc[-1]['close']; price_start=df.iloc[0]['close']
            bh=(price_now/price_start-1)*100
            p(f"   {len(df)} velas | ${price_start:.4f} → ${price_now:.4f} (B&H: {bh:+.1f}%)")
            
            strategies = []
            
            # ═══ ESTRATEGIA 1: Triple Dip ═══
            # RSI<30 + Stochastic<20 + precio cerca de BB inferior
            # = sobreventa confirmada por 3 indicadores
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    safe(r,'RSI') < 35 and safe(p,'RSI') < 35 and safe(r,'RSI') > safe(p,'RSI') and  # RSI bajo y subiendo
                    safe(r,'SK',50) < 25 and  # Stochastic también bajo
                    r['close'] < safe(r,'BBM',r['close']*2)  # Bajo la media de Bollinger
                ),
                exit_fn=lambda r,p,d,i: safe(r,'RSI') > 65 or safe(r,'SK',50) > 80,
                sl_pct=4, tp_pct=8, label='Triple Dip (RSI+Stoch+BB)'))
            
            # ═══ ESTRATEGIA 2: Momentum Confirmado ═══
            # RSI cruzando 40 hacia arriba + MACD cruzando + volumen alto
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    safe(p,'RSI') < 42 and safe(r,'RSI') > 42 and  # RSI cruza 42
                    safe(r,'MACD',0) > safe(r,'MACD_S',0) and  # MACD positivo
                    safe(r,'VOL_RATIO',1) > 1.3  # Volumen 30% encima media
                ),
                exit_fn=lambda r,p,d,i: safe(r,'RSI') > 70 or safe(r,'MACD',0) < safe(r,'MACD_S',0),
                sl_pct=3, tp_pct=6, label='Momentum Confirmado (RSI+MACD+Vol)'))

            # ═══ ESTRATEGIA 3: Doble Bounce ═══
            # 2 velas rojas seguidas + RSI<35 + rebote (vela verde)
            # = caída confirmada que empieza a rebotar
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    p2.get('BEAR',False) and p.get('BEAR',False) and  # 2 velas rojas previas
                    r.get('BULL',False) and  # Vela actual verde (rebote)
                    safe(r,'RSI') < 38 and  # RSI bajo
                    safe(r,'RSI') > safe(p,'RSI')  # RSI subiendo
                ),
                exit_fn=lambda r,p,d,i: safe(r,'RSI') > 65,
                sl_pct=4, tp_pct=7, label='Doble Bounce (2Rojas+Verde+RSI)'))
            
            # ═══ ESTRATEGIA 4: Trend Sniper ═══
            # Precio > EMA21 (tendencia alcista) + RSI baja a <40 (pullback) + rebota
            # = comprar el retroceso en tendencia alcista
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    r['close'] > safe(r,'E21',0) and  # En tendencia alcista
                    safe(r,'E21',0) > safe(r,'E50',0) and  # EMAs alineadas
                    safe(p,'RSI') < 40 and safe(r,'RSI') > safe(p,'RSI') and  # RSI bajo y subiendo
                    safe(r,'ADX',0) > 20  # Tendencia tiene fuerza
                ),
                exit_fn=lambda r,p,d,i: safe(r,'RSI') > 70 or r['close'] < safe(r,'E21',0),
                sl_pct=3, tp_pct=5, label='Trend Sniper (EMA+RSI+ADX)'))
            
            # ═══ ESTRATEGIA 5: BB Squeeze + Breakout ═══
            # BB se estrecha (volatilidad baja) + precio rompe por arriba
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    safe(r,'BBU',1) > 0 and safe(r,'BBL',0) > 0 and
                    safe(p,'BBU',1) > 0 and safe(p,'BBL',0) > 0 and
                    (safe(r,'BBU') - safe(r,'BBL')) < (safe(p,'BBU') - safe(p,'BBL')) * 0.95 and  # BB estrechándose
                    r['close'] > safe(r,'BBM',r['close']*2) and  # Precio sobre media
                    safe(r,'RSI') > 50 and safe(r,'RSI') < 65 and  # RSI en zona neutral-alta
                    safe(r,'VOL_RATIO',1) > 1.2  # Volumen confirmando
                ),
                exit_fn=lambda r,p,d,i: r['close'] > safe(r,'BBU',r['close']*2) or safe(r,'RSI') > 75,
                sl_pct=3, tp_pct=5, label='BB Squeeze+Break (BB+RSI+Vol)'))
            
            # ═══ ESTRATEGIA 6: Stoch + RSI Double Bottom ═══
            # Stochastic<20 + RSI<30 hace double bottom (segundo mínimo más alto)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    safe(r,'SK',50) < 25 and safe(r,'SK',50) > safe(p,'SK',50) and  # Stoch rebotando
                    safe(r,'RSI') < 35 and safe(r,'RSI') > safe(p,'RSI') and  # RSI rebotando
                    safe(p,'RSI') > safe(p2,'RSI') * 0.98  # No hizo nuevo mínimo (double bottom)
                ),
                exit_fn=lambda r,p,d,i: safe(r,'SK',50) > 80 or safe(r,'RSI') > 70,
                sl_pct=4, tp_pct=8, label='Double Bottom (Stoch+RSI)'))
            
            # ═══ ESTRATEGIA 7: Volume Spike Reversal ═══
            # Gran volumen (>2x media) + vela de reversión (mecha larga abajo)
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    safe(r,'VOL_RATIO',1) > 2.0 and  # Volumen 2x la media
                    r.get('BULL',False) and  # Vela verde
                    (r['close'] - r['low']) > (r['high'] - r['close']) * 2 and  # Mecha inferior larga
                    safe(r,'RSI') < 45  # RSI no está alto
                ),
                exit_fn=lambda r,p,d,i: safe(r,'RSI') > 65,
                sl_pct=3, tp_pct=6, label='Vol Spike Reversal (Vol+Candle)'))
            
            # ═══ ESTRATEGIA 8: EMA Ribbon + Dip ═══
            # EMAs alineadas (5>13>21) + RSI cae a <40 = pullback en tendencia fuerte
            strategies.append(bt(df,
                entry_fn=lambda r,p,p2,d,i: (
                    safe(r,'E5',0) > safe(r,'E13',0) > safe(r,'E21',0) and  # EMAs alineadas alcistas
                    safe(p,'RSI') < 42 and safe(r,'RSI') > safe(p,'RSI') and  # RSI cayó y rebota
                    r['close'] > safe(r,'E13',0)  # Precio rebota sobre EMA13
                ),
                exit_fn=lambda r,p,d,i: safe(r,'E5',0) < safe(r,'E13',0) or safe(r,'RSI') > 72,
                sl_pct=3, tp_pct=5, label='EMA Ribbon Dip (5>13>21+RSI)'))
            
            # Print
            strategies.sort(key=lambda x: x['pnl'], reverse=True)
            p(f"\n   {'Estrategia':<38s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | SL|TP")
            p(f"   {'-'*38}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-----")
            
            for s in strategies:
                e = '🟢' if s['pnl']>0 else ('⚪' if s['trades']==0 else '🔴')
                p(f"   {s['label']:<38s} | {e}${s['pnl']:+5.2f} | {s['trades']:3d} | {s['wr']:3.0f}% | {s['sl']:2d}|{s['tp']:2d}")
            
            with_trades = [s for s in strategies if s['trades']>=2]
            if with_trades:
                best = max(with_trades, key=lambda x: x['pnl'])
                best_wr = max(with_trades, key=lambda x: x['wr'])
                p(f"\n   🏆 MÁS RENTABLE: {best['label']} → ${best['pnl']:+.2f} ({best['trades']}T, {best['wr']:.0f}% WR)")
                p(f"   🎯 MEJOR WR:     {best_wr['label']} → {best_wr['wr']:.0f}% WR ({best_wr['trades']}T, ${best_wr['pnl']:+.2f})")
                all_best[coin] = {'best': best, 'best_wr': best_wr, 'bh': bh, 'all': strategies}
            else:
                p(f"\n   ⚠️ Pocas señales — filtros muy estrictos")
                all_best[coin] = {'best': strategies[0] if strategies else None, 'bh': bh, 'all': strategies}
                
        except Exception as e:
            p(f"   ❌ Error: {e}")
        time.sleep(1)
    
    # ═══ RESUMEN ═══
    p(f"\n{'='*80}")
    p("🏆 RESUMEN FINAL — ESTRATEGIA ÓPTIMA POR MONEDA")
    p(f"{'='*80}")
    
    total = 0; total_trades = 0
    p(f"\n   {'Moneda':<12s} | {'Estrategia':<38s} | {'PnL':>6s} | {'#':>3s} | {'WR':>4s}")
    p(f"   {'-'*12}-+-{'-'*38}-+-{'-'*6}-+-{'-'*3}-+-{'-'*4}")
    
    for coin, d in all_best.items():
        b = d.get('best')
        if b:
            e='🟢' if b['pnl']>0 else '🔴'
            total += b['pnl']; total_trades += b['trades']
            p(f"   {coin:<12s} | {b['label']:<38s} | {e}${b['pnl']:+.2f} | {b['trades']:3d} | {b['wr']:3.0f}%")
    
    p(f"\n   TOTAL: ${total:+.2f} ({total/150*100:+.1f}%) | {total_trades} trades | Promedio: {total_trades/5:.0f}/moneda")
    p(f"\n   Comparativa:")
    p(f"   · RSI<15 conservador:    $+1.44 (+0.9%)  |   5 trades")
    p(f"   · Lab agresivo anterior: $+17.91 (+11.9%) |  35 trades")
    p(f"   · Max trades (bestia):   $-4.50 (-3.0%)  | 198 trades")
    p(f"   · FRANCOTIRADOR (este):   ${total:+.2f} ({total/150*100:+.1f}%) | {total_trades} trades")

if __name__ == '__main__':
    main()
