"""
🎯 LAB SNIPER ROTATIVO: Simulación completa
=============================================
Simula exactamente como funcionará el bot:
- Vigila 5 monedas
- Solo 1 posición a la vez  
- Pone TODO el capital en la MEJOR señal
- Cierra → busca la siguiente
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time
from datetime import datetime

def p(msg): print(msg); sys.stdout.flush()

def safe(row, col, default=50):
    v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return float(v) if v is not None and not pd.isna(v) else default

def score_signal(row, prev):
    """Score 0-100 para señal de compra."""
    rsi7 = safe(row, 'RSI_7', 50)
    rsi7_prev = safe(prev, 'RSI_7', 50)
    
    # Condición base: RSI7 < 25 y subiendo
    if rsi7 >= 25 or rsi7 <= rsi7_prev:
        return 0
    
    score = 0
    score += min((25 - rsi7) * 2, 40)  # RSI más bajo = mejor
    
    vol_r = safe(row, 'VOL_R', 1)
    if vol_r > 2.0: score += 20
    elif vol_r > 1.5: score += 15
    elif vol_r > 1.2: score += 10
    
    macd = safe(row, 'MACD', 0)
    macd_s = safe(row, 'MACD_S', 0)
    if macd > macd_s: score += 10
    
    stoch = safe(row, 'SK', 50)
    if stoch < 20: score += 10
    elif stoch < 30: score += 5
    
    rsi14 = safe(row, 'RSI', 50)
    if rsi14 < 30: score += 5
    
    return score

def main():
    p("="*80)
    p("🎯 SIMULACIÓN SNIPER ROTATIVO")
    p("   5 monedas | $30 total | 1 posición a la vez")
    p("   Solo compra la MEJOR señal → cierra → busca siguiente")
    p("="*80)
    
    ex = ccxt.binance({'timeout':30000, 'enableRateLimit': True})
    coins = ['XRP/USDT','DOGE/USDT','AVAX/USDT','SHIB/USDT','SOL/USDT']
    
    # Descargar datos de todas las monedas
    all_data = {}
    for coin in coins:
        p(f"📥 Descargando {coin}...")
        ohlcv = ex.fetch_ohlcv(coin, '1h', limit=720)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['RSI_7'] = ta.rsi(df['close'], length=7)
        df['VOL_SMA'] = df['volume'].rolling(20).mean()
        df['VOL_R'] = df['volume'] / df['VOL_SMA'].replace(0,1)
        mc = ta.macd(df['close'])
        if mc is not None:
            m1=[c for c in mc.columns if c.startswith('MACD_')]
            m2=[c for c in mc.columns if c.startswith('MACDs_')]
            if m1: df['MACD']=mc[m1[0]]
            if m2: df['MACD_S']=mc[m2[0]]
        st = ta.stoch(df['high'],df['low'],df['close'])
        if st is not None:
            sk=[c for c in st.columns if 'STOCHk' in c]
            if sk: df['SK']=st[sk[0]]
        all_data[coin] = df
        p(f"   ✅ {coin}: {len(df)} velas")
        time.sleep(0.5)
    
    # Alinear timestamps (usar la intersección)
    common_ts = all_data[coins[0]].index
    for coin in coins[1:]:
        common_ts = common_ts.intersection(all_data[coin].index)
    p(f"\n📊 {len(common_ts)} velas comunes ({(common_ts[-1]-common_ts[0]).days} días)")
    
    # ═══ SIMULACIÓN ═══
    bal = 30.0
    pos = None  # {'coin': 'XRP/USDT', 'entry': 1.35, 'amount': 20, 'sl': 1.32, 'tp': 1.39}
    trades = []
    peak = 30.0
    max_dd = 0
    
    for i in range(60, len(common_ts)):
        ts = common_ts[i]
        
        if pos is not None:
            # ── MODO MONITOR ──
            coin = pos['coin']
            price = all_data[coin].loc[ts, 'close']
            rsi7 = safe(all_data[coin].loc[ts], 'RSI_7', 50)
            
            hit_sl = price <= pos['sl']
            hit_tp = price >= pos['tp']
            rsi_exit = rsi7 > 65
            
            if hit_sl or hit_tp or rsi_exit:
                pnl = (price - pos['entry']) * pos['amount']
                bal += pnl
                peak = max(peak, bal)
                dd = (peak - bal) / peak * 100
                max_dd = max(max_dd, dd)
                
                reason = 'SL' if hit_sl else ('TP' if hit_tp else 'RSI')
                dur = i - pos['i']
                trades.append({
                    'coin': coin, 'pnl': pnl, 'reason': reason,
                    'dur': dur, 'entry': pos['entry'], 'exit': price,
                    'pct': (price/pos['entry']-1)*100, 'bal': bal,
                    'ts': ts
                })
                
                emoji = '🟢' if pnl > 0 else '🔴'
                if len(trades) <= 30 or pnl > 1 or pnl < -1:
                    p(f"   {emoji} {ts.strftime('%m/%d %H:%M')} | {coin:12s} | "
                      f"${pnl:+.2f} ({reason}) | Dur:{dur}h | Bal: ${bal:.2f}")
                pos = None
        
        else:
            # ── MODO CAZA ──
            best_coin = None
            best_score = 0
            
            for coin in coins:
                row = all_data[coin].loc[ts]
                if i > 0:
                    prev_ts = common_ts[i-1]
                    prev = all_data[coin].loc[prev_ts]
                else:
                    continue
                
                sc = score_signal(row, prev)
                if sc > best_score:
                    best_score = sc
                    best_coin = coin
            
            if best_coin and best_score >= 20:
                price = all_data[best_coin].loc[ts, 'close']
                amount = (bal * 0.90) / price
                pos = {
                    'coin': best_coin,
                    'entry': price,
                    'amount': amount,
                    'sl': price * 0.98,  # -2%
                    'tp': price * 1.03,  # +3%
                    'i': i,
                    'score': best_score,
                }
    
    # Cerrar posición abierta
    if pos:
        coin = pos['coin']
        price = all_data[coin].iloc[-1]['close']
        pnl = (price - pos['entry']) * pos['amount']
        bal += pnl
        trades.append({'coin':coin,'pnl':pnl,'reason':'END','dur':0,'pct':0,'bal':bal,'ts':common_ts[-1]})
    
    # ═══ RESULTADOS ═══
    p(f"\n{'='*80}")
    p("🏆 RESULTADOS SNIPER ROTATIVO")
    p(f"{'='*80}")
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    days = (common_ts[-1] - common_ts[60]).days
    
    p(f"\n   Capital inicial:  $30.00")
    p(f"   Capital final:    ${bal:.2f}")
    p(f"   PnL total:        ${bal-30:+.2f} ({(bal/30-1)*100:+.1f}%)")
    p(f"   Período:          {days} días")
    p(f"   PnL/día:          ${(bal-30)/max(days,1):.2f}")
    p(f"   Max Drawdown:     {max_dd:.1f}%")
    p(f"\n   Trades totales:   {len(trades)}")
    p(f"   Ganados:          {len(wins)} ({len(wins)/max(len(trades),1)*100:.0f}%)")
    p(f"   Perdidos:         {len(losses)}")
    p(f"   Avg ganancia:     ${sum(t['pnl'] for t in wins)/max(len(wins),1):.2f}")
    p(f"   Avg pérdida:      ${sum(t['pnl'] for t in losses)/max(len(losses),1):.2f}")
    
    # Distribución por moneda
    p(f"\n   📊 Distribución por moneda:")
    for coin in coins:
        ct = [t for t in trades if t['coin'] == coin]
        cw = [t for t in ct if t['pnl'] > 0]
        cpnl = sum(t['pnl'] for t in ct)
        e = '🟢' if cpnl > 0 else '🔴'
        p(f"   {coin:12s}: {len(ct):3d} trades | {e} ${cpnl:+.2f} | WR: {len(cw)/max(len(ct),1)*100:.0f}%")
    
    # Distribución por razón de cierre
    p(f"\n   📊 Razones de cierre:")
    for reason in ['SL', 'TP', 'RSI', 'END']:
        ct = [t for t in trades if t['reason'] == reason]
        if ct:
            cpnl = sum(t['pnl'] for t in ct)
            p(f"   {reason:4s}: {len(ct):3d} trades | ${cpnl:+.2f}")
    
    # Proyección
    p(f"\n   📈 PROYECCIONES:")
    daily = (bal-30)/max(days,1)
    p(f"   Con $30:    ${daily:.2f}/día → ${daily*30:.2f}/mes")
    p(f"   Con $150:   ${daily*5:.2f}/día → ${daily*5*30:.2f}/mes")
    p(f"   Con $600:   ${daily*20:.2f}/día → ${daily*20*30:.2f}/mes")
    p(f"   Con $1,000: ${daily*33:.2f}/día → ${daily*33*30:.2f}/mes")

if __name__ == '__main__':
    main()
