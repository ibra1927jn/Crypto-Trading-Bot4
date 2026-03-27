"""
Diagnóstico rápido: ¿Por qué solo $8 en 3 meses?
"""
import ccxt, pandas as pd, pandas_ta as ta, sys

def bt(data, rsi_entry, sl_pct, tp_pct, rsi_exit=70, cap=30.0):
    pos = None; bal = cap; trades = []; maxdd = 0; peak = cap
    for i in range(50, len(data)):
        r, p, price = data.iloc[i], data.iloc[i-1], data.iloc[i]['close']
        rn, rp = r.get('RSI_14',50), p.get('RSI_14',50)
        if pd.isna(rn) or pd.isna(rp): continue
        if pos is None:
            if rp < rsi_entry and rn > rp:
                amt = (bal*0.8)/price
                pos = {'e':price,'a':amt,'sl':price*(1-sl_pct/100),'tp':price*(1+tp_pct/100),'i':i}
        else:
            if price<=pos['sl'] or price>=pos['tp'] or rn>rsi_exit:
                pnl = (price-pos['e'])*pos['a']
                bal += pnl; peak = max(peak,bal)
                maxdd = max(maxdd, (peak-bal)/peak*100)
                trades.append({'pnl':pnl, 'sl': price<=pos['sl'], 'tp': price>=pos['tp']})
                pos = None
    if pos:
        pnl = (data.iloc[-1]['close']-pos['e'])*pos['a']; bal += pnl
        trades.append({'pnl':pnl,'sl':False,'tp':False})
    w = len([t for t in trades if t['pnl']>0])
    return {'trades':len(trades),'wins':w,'pnl':bal-cap,'wr':w/max(len(trades),1)*100,
            'dd':maxdd,'sl':len([t for t in trades if t['sl']]),
            'tp':len([t for t in trades if t['tp']])}

print("="*80); print("🔎 DIAGNÓSTICO: ¿Por qué solo $8 en 3 meses?"); print("="*80); sys.stdout.flush()

ex = ccxt.binance()
coins = ['BNB/USDT','XRP/USDT']

configs = [
    (15, 4, 8,  70, 'ACTUAL: RSI<15, SL-4%, TP+8%'),
    (20, 4, 8,  70, 'RSI<20, SL-4%, TP+8%'),
    (25, 4, 8,  70, 'RSI<25, SL-4%, TP+8%'),
    (30, 4, 8,  70, 'RSI<30, SL-4%, TP+8%'),
    (35, 4, 8,  70, 'RSI<35, SL-4%, TP+8%'),
    (25, 3, 5,  65, 'RSI<25, SL-3%, TP+5% (rápido)'),
    (30, 2, 3,  60, 'RSI<30, SL-2%, TP+3% (scalp)'),
    (25, 6, 12, 75, 'RSI<25, SL-6%, TP+12% (swing)'),
    (30, 5, 10, 75, 'RSI<30, SL-5%, TP+10%'),
]

for coin in coins:
    print(f"\n📊 {coin}"); sys.stdout.flush()
    ohlcv = ex.fetch_ohlcv(coin, '5m', limit=1000)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    
    rsi = df['RSI_14'].dropna()
    print(f"   {len(df)} velas (últimos ~3.5 días)")
    for lvl in [15,20,25,30,35,40]:
        cnt = len(rsi[rsi<lvl])
        print(f"   RSI<{lvl}: {cnt} velas ({cnt/len(rsi)*100:.1f}%)")
    sys.stdout.flush()
    
    print(f"\n   {'Config':<38s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | {'DD':>5s} | SL|TP")
    print(f"   {'-'*38}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-{'-'*5}-+-----")
    
    for rsi_e, sl, tp, rsi_x, label in configs:
        r = bt(df, rsi_e, sl, tp, rsi_x)
        e = '🟢' if r['pnl']>0 else ('⚪' if r['pnl']==0 else '🔴')
        print(f"   {label:<38s} | {e}${r['pnl']:+5.2f} | {r['trades']:3d} | {r['wr']:3.0f}% | {r['dd']:4.1f}% | {r['sl']:2d}|{r['tp']:2d}")
    sys.stdout.flush()

# Now download MORE data (1000 candles of 1h = ~42 days)
print(f"\n{'='*80}")
print("📊 MISMA PRUEBA CON 42 DÍAS (velas de 1h)")
print(f"{'='*80}"); sys.stdout.flush()

for coin in coins:
    print(f"\n📊 {coin} (1h, 42 días)"); sys.stdout.flush()
    ohlcv = ex.fetch_ohlcv(coin, '1h', limit=1000)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    
    rsi = df['RSI_14'].dropna()
    print(f"   {len(df)} velas")
    for lvl in [15,20,25,30,35]:
        cnt = len(rsi[rsi<lvl])
        print(f"   RSI<{lvl}: {cnt} velas ({cnt/len(rsi)*100:.1f}%)")
    sys.stdout.flush()
    
    print(f"\n   {'Config':<38s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | {'DD':>5s}")
    print(f"   {'-'*38}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-{'-'*5}")
    
    for rsi_e, sl, tp, rsi_x, label in configs:
        r = bt(df, rsi_e, sl, tp, rsi_x)
        e = '🟢' if r['pnl']>0 else ('⚪' if r['pnl']==0 else '🔴')
        print(f"   {label:<38s} | {e}${r['pnl']:+5.2f} | {r['trades']:3d} | {r['wr']:3.0f}% | {r['dd']:4.1f}%")
    sys.stdout.flush()

print(f"\n{'='*80}")
print("💡 CONCLUSIÓN")
print(f"{'='*80}")
print("Si RSI<15 da 0-2 trades, ese es el problema: el bot NUNCA opera.")
print("RSI<25 o RSI<30 debería dar MÁS trades con riesgo aceptable.")
print("La clave es encontrar el balance entre frecuencia y calidad.")
sys.stdout.flush()
