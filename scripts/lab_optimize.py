"""
🔧 Optimizar SL/TP para el Sniper Rotativo
Sweep de parámetros: SL 1%-5%, TP 2%-10%, RSI entry 20-35
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time

def p(msg): print(msg); sys.stdout.flush()

def safe(row, col, default=50):
    v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return float(v) if v is not None and not pd.isna(v) else default

def sim(all_data, common_ts, rsi_entry=25, sl_pct=2, tp_pct=3, rsi_exit=65, cap=30.0):
    bal=cap; pos=None; trades=[]
    coins = list(all_data.keys())
    for i in range(60, len(common_ts)):
        ts = common_ts[i]
        if pos:
            price = all_data[pos['coin']].loc[ts,'close']
            rsi7 = safe(all_data[pos['coin']].loc[ts],'RSI_7',50)
            if price<=pos['sl'] or price>=pos['tp'] or rsi7>rsi_exit:
                pnl=(price-pos['entry'])*pos['amount']; bal+=pnl
                trades.append({'pnl':pnl,'r':'SL' if price<=pos['sl'] else ('TP' if price>=pos['tp'] else 'RSI')})
                pos=None
        else:
            best_c=None; best_s=0
            for coin in coins:
                row=all_data[coin].loc[ts]; prev=all_data[coin].loc[common_ts[i-1]]
                r7=safe(row,'RSI_7',50); r7p=safe(prev,'RSI_7',50)
                if r7<rsi_entry and r7>r7p:
                    sc=(rsi_entry-r7)*2
                    vr=safe(row,'VOL_R',1)
                    if vr>1.5: sc+=15
                    elif vr>1.2: sc+=10
                    if safe(row,'MACD',0)>safe(row,'MACD_S',0): sc+=10
                    if safe(row,'SK',50)<20: sc+=10
                    if sc>best_s: best_s=sc; best_c=coin
            if best_c and best_s>=15:
                price=all_data[best_c].loc[ts,'close']
                amt=(bal*0.90)/price
                pos={'coin':best_c,'entry':price,'amount':amt,
                     'sl':price*(1-sl_pct/100),'tp':price*(1+tp_pct/100),'i':i}
    if pos:
        price=all_data[pos['coin']].iloc[-1]['close']
        pnl=(price-pos['entry'])*pos['amount']; bal+=pnl
        trades.append({'pnl':pnl,'r':'END'})
    w=len([t for t in trades if t['pnl']>0]); n=len(trades)
    return {'trades':n,'wins':w,'pnl':bal-cap,'wr':w/max(n,1)*100,'bal':bal}

def main():
    p("="*80)
    p("🔧 OPTIMIZACIÓN SNIPER ROTATIVO — SWEEP SL/TP/RSI")
    p("="*80)
    
    ex = ccxt.binance({'timeout':30000,'enableRateLimit':True})
    coins = ['XRP/USDT','DOGE/USDT','AVAX/USDT','SHIB/USDT','SOL/USDT']
    
    all_data = {}
    for coin in coins:
        ohlcv = ex.fetch_ohlcv(coin, '1h', limit=720)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df['RSI_7'] = ta.rsi(df['close'], length=7)
        df['VOL_SMA'] = df['volume'].rolling(20).mean()
        df['VOL_R'] = df['volume'] / df['VOL_SMA'].replace(0,1)
        mc=ta.macd(df['close'])
        if mc is not None:
            m1=[c for c in mc.columns if c.startswith('MACD_')]
            m2=[c for c in mc.columns if c.startswith('MACDs_')]
            if m1: df['MACD']=mc[m1[0]]
            if m2: df['MACD_S']=mc[m2[0]]
        st=ta.stoch(df['high'],df['low'],df['close'])
        if st is not None:
            sk=[c for c in st.columns if 'STOCHk' in c]
            if sk: df['SK']=st[sk[0]]
        all_data[coin] = df
        time.sleep(0.3)
    
    common_ts = all_data[coins[0]].index
    for coin in coins[1:]:
        common_ts = common_ts.intersection(all_data[coin].index)
    p(f"\n{len(common_ts)} velas comunes\n")
    
    # Sweep
    results = []
    configs = [
        # (rsi_entry, sl, tp, rsi_exit, label)
        (25, 2, 3, 65, 'RSI<25 SL2/TP3 (base)'),
        (25, 1.5, 3, 65, 'RSI<25 SL1.5/TP3'),
        (25, 2, 5, 70, 'RSI<25 SL2/TP5'),
        (25, 3, 5, 70, 'RSI<25 SL3/TP5'),
        (25, 2, 4, 65, 'RSI<25 SL2/TP4'),
        (25, 3, 6, 70, 'RSI<25 SL3/TP6'),
        (25, 4, 8, 70, 'RSI<25 SL4/TP8 (swing)'),
        (25, 5, 10, 75, 'RSI<25 SL5/TP10 (big swing)'),
        (30, 2, 3, 65, 'RSI<30 SL2/TP3'),
        (30, 2, 5, 70, 'RSI<30 SL2/TP5'),
        (30, 3, 5, 70, 'RSI<30 SL3/TP5'),
        (30, 3, 6, 70, 'RSI<30 SL3/TP6'),
        (30, 4, 8, 70, 'RSI<30 SL4/TP8'),
        (30, 5, 10, 75, 'RSI<30 SL5/TP10'),
        (35, 2, 4, 65, 'RSI<35 SL2/TP4'),
        (35, 3, 5, 65, 'RSI<35 SL3/TP5'),
        (35, 3, 6, 70, 'RSI<35 SL3/TP6'),
        (35, 4, 8, 70, 'RSI<35 SL4/TP8'),
        (35, 5, 10, 75, 'RSI<35 SL5/TP10'),
        (40, 3, 5, 65, 'RSI<40 SL3/TP5'),
        (40, 3, 6, 65, 'RSI<40 SL3/TP6'),
        (40, 4, 8, 70, 'RSI<40 SL4/TP8'),
    ]
    
    p(f"{'Config':<30s} | {'PnL':>7s} | {'#':>3s} | {'WR':>4s} | {'$/día':>6s}")
    p(f"{'-'*30}-+-{'-'*7}-+-{'-'*3}-+-{'-'*4}-+-{'-'*6}")
    
    for rsi_e, sl, tp, rsi_x, label in configs:
        r = sim(all_data, common_ts, rsi_e, sl, tp, rsi_x)
        days = 27
        daily = r['pnl']/days if days > 0 else 0
        e = '🟢' if r['pnl']>0 else ('⚪' if r['trades']==0 else '🔴')
        p(f"{label:<30s} | {e}${r['pnl']:+5.2f} | {r['trades']:3d} | {r['wr']:3.0f}% | ${daily:+.2f}")
        results.append({**r, 'label': label, 'daily': daily})
    
    # Top 5
    results.sort(key=lambda x: x['pnl'], reverse=True)
    p(f"\n🏆 TOP 5:")
    for i, r in enumerate(results[:5]):
        p(f"   {i+1}. {r['label']} → ${r['pnl']:+.2f} | {r['trades']}T | {r['wr']:.0f}% WR | ${r['daily']:+.2f}/día")
    
    best = results[0]
    p(f"\n   Mejor con $30:    ${best['daily']:.2f}/día → ${best['daily']*30:.2f}/mes")
    p(f"   Mejor con $150:   ${best['daily']*5:.2f}/día → ${best['daily']*5*30:.2f}/mes")
    p(f"   Mejor con $600:   ${best['daily']*20:.2f}/día → ${best['daily']*20*30:.2f}/mes")
    p(f"   Mejor con $1,000: ${best['daily']*33:.2f}/día → ${best['daily']*33*30:.2f}/mes")

if __name__ == '__main__':
    main()
