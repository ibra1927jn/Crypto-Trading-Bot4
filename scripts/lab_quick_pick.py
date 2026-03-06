"""
Quick Lab: XRP/DOGE/SOL/BNB con AllIn RSI<15
=============================================
Test rápido con datos reales de Binance para elegir la mejor moneda.
"""
import ccxt
import pandas as pd
import pandas_ta as ta
from datetime import datetime

def run_backtest(symbol, data, strategy='ALLIN_RSI', capital=30.0):
    """Backtest rápido de una estrategia en un par."""
    position = None
    trades = []
    balance = capital
    
    for i in range(50, len(data)):
        row = data.iloc[i]
        prev = data.iloc[i-1]
        price = row['close']
        
        if position is None:
            # ENTRY: AllIn RSI<15
            rsi_prev = prev.get('RSI_14', 50)
            rsi_now = row.get('RSI_14', 50)
            ema50 = row.get('EMA_50', price)
            
            if pd.isna(rsi_prev) or pd.isna(rsi_now) or pd.isna(ema50):
                continue
                
            if rsi_prev < 15 and rsi_now > rsi_prev and price > ema50 * 0.95:
                amount = (balance * 0.80) / price
                position = {
                    'entry': price,
                    'amount': amount,
                    'sl': price * 0.96,  # -4%
                    'tp': price * 1.08,  # +8%
                    'entry_i': i,
                }
        else:
            # EXIT checks
            hit_sl = price <= position['sl']
            hit_tp = price >= position['tp']
            
            rsi_now = row.get('RSI_14', 50)
            if pd.isna(rsi_now):
                rsi_now = 50
            rsi_exit = rsi_now > 70
            
            if hit_sl or hit_tp or rsi_exit:
                pnl = (price - position['entry']) * position['amount']
                balance += pnl
                reason = 'SL' if hit_sl else ('TP' if hit_tp else 'RSI>70')
                trades.append({
                    'entry': position['entry'],
                    'exit': price,
                    'pnl': pnl,
                    'reason': reason,
                    'duration': i - position['entry_i'],
                })
                position = None
    
    # Close any open position at end
    if position:
        price = data.iloc[-1]['close']
        pnl = (price - position['entry']) * position['amount']
        balance += pnl
        trades.append({
            'entry': position['entry'],
            'exit': price,
            'pnl': pnl,
            'reason': 'END',
            'duration': len(data) - position['entry_i'],
        })
    
    return {
        'symbol': symbol,
        'trades': len(trades),
        'wins': len([t for t in trades if t['pnl'] > 0]),
        'losses': len([t for t in trades if t['pnl'] <= 0]),
        'total_pnl': balance - capital,
        'final_balance': balance,
        'wr': len([t for t in trades if t['pnl'] > 0]) / max(len(trades), 1) * 100,
        'bh_return': (data.iloc[-1]['close'] / data.iloc[0]['close'] - 1) * capital,
        'max_dd': min([t['pnl'] for t in trades]) if trades else 0,
    }

def main():
    print("=" * 70)
    print("🧪 QUICK LAB: XRP/DOGE/SOL/BNB con AllIn RSI<15")
    print(f"📊 Capital: $30 | Posición: 80% | SL: -4% | TP: +8%")
    print(f"📅 Datos: últimos 3 meses de Binance REAL (mainnet)")
    print("=" * 70)
    
    ex = ccxt.binance()
    symbols = ['XRP/USDT', 'DOGE/USDT', 'SOL/USDT', 'BNB/USDT']
    results = []
    
    for sym in symbols:
        print(f"\n📥 Descargando {sym}...")
        try:
            # 3 meses de velas 5m
            all_ohlcv = []
            since = ex.parse8601('2025-12-06T00:00:00Z')
            while True:
                ohlcv = ex.fetch_ohlcv(sym, '5m', since=since, limit=1000)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                if since > ex.milliseconds():
                    break
                if len(all_ohlcv) > 25000:
                    break
            
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='last')]
            
            # Indicadores
            df['RSI_14'] = ta.rsi(df['close'], length=14)
            df['EMA_50'] = ta.ema(df['close'], length=50)
            
            print(f"  ✅ {len(df)} velas | Precio actual: ${df.iloc[-1]['close']:.4f}")
            print(f"  📊 Range: ${df['close'].min():.4f} → ${df['close'].max():.4f}")
            
            result = run_backtest(sym, df, capital=30.0)
            results.append(result)
            
            pnl_emoji = '🟢' if result['total_pnl'] > 0 else '🔴'
            print(f"  {pnl_emoji} PnL: ${result['total_pnl']:.2f} | "
                  f"Trades: {result['trades']} | WR: {result['wr']:.0f}% | "
                  f"B&H: ${result['bh_return']:.2f}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # Rankings
    print("\n" + "=" * 70)
    print("🏆 RANKING FINAL — AllIn RSI<15 en las 4 monedas")
    print("=" * 70)
    results.sort(key=lambda x: x['total_pnl'], reverse=True)
    
    for i, r in enumerate(results):
        medal = ['🥇', '🥈', '🥉', '4️⃣'][i]
        pnl_emoji = '🟢' if r['total_pnl'] > 0 else '🔴'
        print(f"{medal} {r['symbol']:12s} | {pnl_emoji} PnL: ${r['total_pnl']:+.2f} | "
              f"Trades: {r['trades']:2d} | WR: {r['wr']:.0f}% | "
              f"B&H: ${r['bh_return']:+.2f} | MaxDD: ${r['max_dd']:.2f}")
    
    if results and results[0]['total_pnl'] > 0:
        print(f"\n✅ RECOMENDACIÓN: Empezar con {results[0]['symbol']}")
    elif results:
        print(f"\n⚠️ Ninguna moneda fue claramente positiva. La menos mala: {results[0]['symbol']}")

if __name__ == '__main__':
    main()
