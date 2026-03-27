"""
🔬 DIAGNÓSTICO: ¿Cuántos trades/día podemos hacer con 5min?
============================================================
Prueba múltiples estrategias en paralelo para maximizar trades
manteniendo 70%+ WR. Target: 5-10 trades/día.
"""
import sys, ccxt, pandas as pd, pandas_ta as ta, time
from datetime import datetime

def p(msg): print(msg); sys.stdout.flush()

def safe(row, col, default=0):
    v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
    return float(v) if v is not None and not pd.isna(v) else default

def add_indicators(df):
    df['RSI_7'] = ta.rsi(df['close'], length=7)
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    df['EMA_9'] = ta.ema(df['close'], 9)
    df['EMA_21'] = ta.ema(df['close'], 21)
    df['EMA_50'] = ta.ema(df['close'], 50)
    df['VOL_SMA'] = df['volume'].rolling(20).mean()
    df['VOL_R'] = df['volume'] / df['VOL_SMA'].replace(0, 1e-10)
    mc = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if mc is not None:
        for px, nm in [('MACD_', 'MACD'), ('MACDs_', 'MACD_S')]:
            cc = [c for c in mc.columns if c.startswith(px)]
            if cc: df[nm] = mc[cc[0]]
    bb = ta.bbands(df['close'], length=20, std=2)
    if bb is not None:
        for px, nm in [('BBL_', 'BB_LO'), ('BBM_', 'BB_MID'), ('BBU_', 'BB_HI')]:
            cc = [c for c in bb.columns if c.startswith(px)]
            if cc: df[nm] = bb[cc[0]]
    st = ta.stoch(df['high'], df['low'], df['close'])
    if st is not None:
        sk = [c for c in st.columns if 'STOCHk' in c]
        if sk: df['SK'] = st[sk[0]]
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    # Porcentaje de cambio de la vela
    df['CANDLE_PCT'] = (df['close'] - df['open']) / df['open'] * 100
    # Distancia al Bollinger inferior
    df['BB_POS'] = (df['close'] - df.get('BB_LO', df['close'])) / (
        df.get('BB_HI', df['close']) - df.get('BB_LO', df['close']) + 1e-10)
    return df

def check_entry(row, prev, strategies):
    """Evalúa múltiples estrategias y devuelve la primera que se active."""
    for name, fn in strategies.items():
        if fn(row, prev):
            return name
    return None

def sim_multi(df, strategies, sl_pct, tp_pct, cap=30.0, rsi_exit=70):
    """Simula con múltiples entradas."""
    bal = cap
    pos = None
    trades = []
    
    for i in range(60, len(df)):
        row = df.iloc[i]
        
        if pos:
            price = row['close']
            # Trailing
            gain = (price - pos['entry']) / pos['entry'] * 100
            if gain > 1.0:
                new_sl = price * (1 - 1.0/100)
                if new_sl > pos['sl']:
                    pos['sl'] = new_sl
            
            hit_sl = price <= pos['sl']
            hit_tp = price >= pos['tp']
            rsi_out = safe(row, 'RSI_7', 50) > rsi_exit
            
            if hit_sl or hit_tp or rsi_out:
                pnl = (price - pos['entry']) * pos['amount']
                bal += pnl
                reason = 'SL' if hit_sl else ('TP' if hit_tp else 'RSI')
                trades.append({
                    'pnl': pnl, 'reason': reason, 'strat': pos['strat'],
                    'pct': (price/pos['entry']-1)*100, 'bal': bal,
                    'ts': df.index[i],
                })
                pos = None
        else:
            prev = df.iloc[i-1]
            strat = check_entry(row, prev, strategies)
            if strat:
                price = row['close']
                amount = (bal * 0.90) / price
                pos = {
                    'entry': price, 'amount': amount,
                    'sl': price * (1 - sl_pct/100),
                    'tp': price * (1 + tp_pct/100),
                    'strat': strat, 'i': i,
                }
    
    if pos:
        price = df.iloc[-1]['close']
        pnl = (price - pos['entry']) * pos['amount']
        bal += pnl
        trades.append({'pnl': pnl, 'reason': 'END', 'strat': pos['strat'], 'pct': 0, 'bal': bal, 'ts': df.index[-1]})
    
    return trades, bal

def main():
    p("="*80)
    p("🔬 DIAGNÓSTICO: ¿Cuántos trades/día con 5min candles?")
    p("   Target: 5-10 trades/día, 70%+ WR, $30 capital")
    p("="*80)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    coins = ['XRP/USDT', 'DOGE/USDT', 'AVAX/USDT', 'SHIB/USDT', 'SOL/USDT']
    
    # === ESTRATEGIAS DE ENTRADA ===
    strategies = {
        'RSI7_OB': lambda r, p: (  # RSI7 oversold bounce
            safe(r, 'RSI_7', 50) < 25 and safe(r, 'RSI_7', 50) > safe(p, 'RSI_7', 50)
        ),
        'RSI7_30': lambda r, p: (  # RSI7 < 30 + rising
            safe(r, 'RSI_7', 50) < 30 and safe(r, 'RSI_7', 50) > safe(p, 'RSI_7', 50)
            and safe(r, 'VOL_R', 1) > 1.2
        ),
        'BB_BOUNCE': lambda r, p: (  # Precio toca Bollinger inferior + rebote
            safe(r, 'BB_POS', 0.5) < 0.1
            and r['close'] > r['open']  # Vela verde
            and safe(r, 'RSI_7', 50) < 40
        ),
        'EMA_CROSS': lambda r, p: (  # EMA9 cruza sobre EMA21
            safe(p, 'EMA_9', 0) < safe(p, 'EMA_21', 0)
            and safe(r, 'EMA_9', 0) > safe(r, 'EMA_21', 0)
            and safe(r, 'RSI_7', 50) < 55
        ),
        'MACD_CROSS': lambda r, p: (  # MACD cruza señal hacia arriba + RSI bajo
            safe(p, 'MACD', 0) < safe(p, 'MACD_S', 0)
            and safe(r, 'MACD', 0) > safe(r, 'MACD_S', 0)
            and safe(r, 'RSI_7', 50) < 45
        ),
        'DIP_BUY': lambda r, p: (  # Vela roja fuerte seguida de verde + volumen
            safe(p, 'CANDLE_PCT', 0) < -0.5
            and r['close'] > r['open']  # Vela verde
            and safe(r, 'VOL_R', 1) > 1.5
            and safe(r, 'RSI_7', 50) < 40
        ),
        'STOCH_OB': lambda r, p: (  # Stochastic oversold + rebote
            safe(p, 'SK', 50) < 15
            and safe(r, 'SK', 50) > safe(p, 'SK', 50)
            and safe(r, 'RSI_7', 50) < 35
        ),
    }
    
    # === SL/TP CONFIGS ===
    configs = [
        (1.0, 1.5, 70, 'SL1.0/TP1.5'),
        (1.0, 2.0, 70, 'SL1.0/TP2.0'),
        (1.5, 2.0, 70, 'SL1.5/TP2.0'),
        (1.5, 2.5, 70, 'SL1.5/TP2.5'),
        (1.0, 1.5, 65, 'SL1.0/TP1.5 RE65'),
        (0.8, 1.2, 65, 'SL0.8/TP1.2 (scalp)'),
    ]
    
    for coin in coins:
        p(f"\n{'='*60}")
        p(f"📊 {coin}")
        p(f"{'='*60}")
        
        ohlcv = ex.fetch_ohlcv(coin, '5m', limit=1000)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = add_indicators(df)
        
        days = (df.index[-1] - df.index[60]).days or 1
        p(f"   {len(df)} velas ({days} días)")
        
        # Test cada config
        for sl, tp, rsi_x, label in configs:
            trades, bal = sim_multi(df, strategies, sl, tp, rsi_exit=rsi_x)
            w = len([t for t in trades if t['pnl'] > 0])
            n = len(trades)
            pnl = bal - 30
            tpd = n / max(days, 1)
            wr = w / max(n, 1) * 100
            
            e = '🟢' if pnl > 0 else ('⚪' if n == 0 else '🔴')
            p(f"   {label:20s}: {e} ${pnl:+5.2f} | {n:3d}T ({tpd:.1f}/d) | WR:{wr:.0f}%")
            
            # Detalle por estrategia
            if label == 'SL1.0/TP1.5' and n > 0:
                by_strat = {}
                for t in trades:
                    s = t['strat']
                    if s not in by_strat: by_strat[s] = {'n': 0, 'w': 0, 'pnl': 0}
                    by_strat[s]['n'] += 1
                    if t['pnl'] > 0: by_strat[s]['w'] += 1
                    by_strat[s]['pnl'] += t['pnl']
                
                p(f"   {'':20s}  Estrategias:")
                for s, d in sorted(by_strat.items(), key=lambda x: -x[1]['n']):
                    swr = d['w'] / max(d['n'], 1) * 100
                    se = '🟢' if d['pnl'] > 0 else '🔴'
                    p(f"   {'':20s}  {s:12s}: {d['n']:3d}T | WR:{swr:.0f}% | {se} ${d['pnl']:+.2f}")
        
        time.sleep(0.5)
    
    p(f"\n{'='*80}")
    p("📋 RESUMEN: Con SL1.0/TP1.5 necesitamos ~5-10 trades/día")
    p("   Si WR > 70%: cada trade gana ~$0.40, pierde ~$0.27")
    p("   5 trades/día × 70% WR = 3.5 wins × $0.40 - 1.5 losses × $0.27")
    p("   = $1.40 - $0.41 = ~$1.00/día potencial con $30")
    p("="*80)

if __name__ == '__main__':
    main()
