"""
CT4 Lab — Battle Royale: 5 Estrategias Nuevas vs Momentum Adaptativa
=====================================================================
Prueba las 5 nuevas estrategias contra datos reales:
  1. Grid Trading
  2. DCA Inteligente
  3. Mean Reversion (Bollinger)
  4. Breakout Confirmado
  5. Multi-Asset Rotation (BTC vs ETH vs SOL)
  + Momentum Adaptativa (referencia)
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

TIMEFRAME = "5m"
INITIAL_CAPITAL = 10000

def calc_indicators(df):
    df['EMA_9'] = df['close'].ewm(span=9).mean()
    df['EMA_21'] = df['close'].ewm(span=21).mean()
    df['EMA_200'] = df['close'].ewm(span=200).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([high-low, abs(high-close.shift(1)), abs(low-close.shift(1))], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    
    plus_dm = high.diff().where(lambda x: (x > 0) & (x > -low.diff()), 0)
    minus_dm = (-low.diff()).where(lambda x: (x > 0) & (x > high.diff()), 0)
    plus_di = 100 * (plus_dm.rolling(14).mean() / df['ATR'])
    minus_di = 100 * (minus_dm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    df['ADX'] = dx.rolling(14).mean()
    
    df['VOL_SMA'] = df['volume'].rolling(20).mean()
    
    df['BB_MID'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['BB_UPPER'] = df['BB_MID'] + 2 * bb_std
    df['BB_LOWER'] = df['BB_MID'] - 2 * bb_std
    df['BB_PCT'] = (df['close'] - df['BB_LOWER']) / (df['BB_UPPER'] - df['BB_LOWER'] + 1e-10)
    
    df['HIGH_24'] = df['high'].rolling(288).max()   # 288 velas de 5min = 24h
    df['LOW_24'] = df['low'].rolling(288).min()
    df['MOM_10'] = df['close'].pct_change(10) * 100
    
    return df

# ═══════════════════════════════════════════════════════════
# ESTRATEGIA 1: GRID TRADING
# ═══════════════════════════════════════════════════════════
def run_grid(df, grid_pct=0.005, num_grids=10):
    """Grid Trading: compra cada -X%, vende cada +X%."""
    capital = INITIAL_CAPITAL
    holdings = 0  # BTC owned
    trades = []
    
    start_price = df.iloc[200]['close']
    grid_levels_buy = [start_price * (1 - grid_pct * i) for i in range(1, num_grids+1)]
    grid_levels_sell = [start_price * (1 + grid_pct * i) for i in range(1, num_grids+1)]
    filled_buys = set()
    filled_sells = set()
    
    for i in range(201, len(df)):
        price = df.iloc[i]['close']
        
        # Check buy levels
        for j, level in enumerate(grid_levels_buy):
            if j not in filled_buys and price <= level and capital >= 100:
                buy_amount = 100 / price  # $100 per grid
                capital -= 100
                holdings += buy_amount
                filled_buys.add(j)
                trades.append({'type': 'BUY', 'price': price, 'pnl': 0})
        
        # Check sell levels
        for j, level in enumerate(grid_levels_sell):
            if j not in filled_sells and price >= level and holdings > 0:
                sell_amount = min(holdings, 100 / price)
                capital += sell_amount * price
                holdings -= sell_amount
                filled_sells.add(j)
                profit = sell_amount * (price - start_price)
                trades.append({'type': 'SELL', 'price': price, 'pnl': profit})
    
    # Close remaining
    final = capital + holdings * df.iloc[-1]['close']
    return {
        'name': '1. GRID TRADING',
        'trades': len(trades),
        'pnl': final - INITIAL_CAPITAL,
        'return_pct': ((final - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100,
        'capital': final,
        'buys': len([t for t in trades if t['type'] == 'BUY']),
        'sells': len([t for t in trades if t['type'] == 'SELL']),
    }

# ═══════════════════════════════════════════════════════════
# ESTRATEGIA 2: DCA INTELIGENTE
# ═══════════════════════════════════════════════════════════
def run_dca(df, buy_interval=36, base_amount=50):
    """DCA Inteligente: compra cada N velas, dobla si RSI < 30."""
    capital = INITIAL_CAPITAL
    holdings = 0
    trades = []
    total_invested = 0
    
    for i in range(201, len(df)):
        if (i - 201) % buy_interval != 0:
            continue
        
        row = df.iloc[i]
        rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
        
        # DCA inteligente: más si RSI está bajo
        if rsi < 20:
            amount = base_amount * 3   # Triple
        elif rsi < 30:
            amount = base_amount * 2   # Double
        elif rsi > 70:
            amount = base_amount * 0.5  # Half
        else:
            amount = base_amount
        
        if capital >= amount:
            buy_qty = amount / row['close']
            capital -= amount
            holdings += buy_qty
            total_invested += amount
            trades.append({'type': 'BUY', 'price': row['close'], 'amount': amount, 'rsi': rsi})
    
    final = capital + holdings * df.iloc[-1]['close']
    avg_price = total_invested / holdings if holdings > 0 else 0
    
    return {
        'name': '2. DCA INTELIGENTE',
        'trades': len(trades),
        'pnl': final - INITIAL_CAPITAL,
        'return_pct': ((final - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100,
        'capital': final,
        'avg_price': avg_price,
        'holdings': holdings,
        'invested': total_invested,
    }

# ═══════════════════════════════════════════════════════════
# ESTRATEGIA 3: MEAN REVERSION (BOLLINGER)
# ═══════════════════════════════════════════════════════════
def run_mean_reversion(df):
    """Compra en banda inferior de Bollinger, vende en banda superior."""
    capital = INITIAL_CAPITAL
    position = None
    trades = []
    
    for i in range(201, len(df)-1):
        row = df.iloc[i]
        
        if pd.isna(row['BB_PCT']):
            continue
        
        if position is None:
            # Buy near lower Bollinger Band
            if row['BB_PCT'] < 0.1 and row['RSI'] < 35:
                size = (capital * 0.3) / row['close']
                position = {'entry': row['close'], 'size': size}
        else:
            # Sell near upper band or at mid
            if row['BB_PCT'] > 0.85 or row['RSI'] > 65:
                pnl = (row['close'] - position['entry']) * position['size']
                capital += pnl
                trades.append({
                    'entry': position['entry'], 'exit': row['close'],
                    'pnl': pnl, 'pct': (pnl/(position['entry']*position['size']))*100
                })
                position = None
            # SL: price drops below lower band by 1%
            elif row['close'] < row['BB_LOWER'] * 0.99:
                pnl = (row['close'] - position['entry']) * position['size']
                capital += pnl
                trades.append({
                    'entry': position['entry'], 'exit': row['close'],
                    'pnl': pnl, 'pct': (pnl/(position['entry']*position['size']))*100
                })
                position = None
    
    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['size']
        capital += pnl
        trades.append({'entry': position['entry'], 'exit': df.iloc[-1]['close'], 'pnl': pnl, 'pct': 0})
    
    wins = [t for t in trades if t['pnl'] > 0]
    return {
        'name': '3. MEAN REVERSION',
        'trades': len(trades),
        'wins': len(wins),
        'win_rate': len(wins)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades),
        'return_pct': ((capital - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100,
        'capital': capital,
    }

# ═══════════════════════════════════════════════════════════
# ESTRATEGIA 4: BREAKOUT CONFIRMADO
# ═══════════════════════════════════════════════════════════
def run_breakout(df):
    """Compra cuando precio rompe máximo de 24h con volumen alto."""
    capital = INITIAL_CAPITAL
    position = None
    trades = []
    cooldown = 0
    
    for i in range(290, len(df)-1):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        if cooldown > 0:
            cooldown -= 1
        
        if pd.isna(row.get('HIGH_24')) or pd.isna(row.get('ADX')):
            continue
        
        if position is None and cooldown == 0:
            # Breakout: new 24h high + volume + ADX
            prev_high = df.iloc[i-1].get('HIGH_24', 0)
            if (row['close'] > prev_high and 
                row['volume'] > row['VOL_SMA'] * 1.2 and
                row['ADX'] > 25):
                
                atr = row['ATR'] if not pd.isna(row['ATR']) else 100
                size = (capital * 0.25) / row['close']
                position = {
                    'entry': row['close'], 'size': size,
                    'sl': row['close'] - 1.5 * atr,
                    'tp': row['close'] + 3.0 * atr
                }
        elif position:
            price = row['close']
            if price <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['size']
                capital += pnl
                trades.append({'pnl': pnl, 'type': 'SL'})
                position = None
                cooldown = 12  # 1 hora de cooldown
            elif price >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['size']
                capital += pnl
                trades.append({'pnl': pnl, 'type': 'TP'})
                position = None
                cooldown = 6
            elif row['ADX'] < 15:  # Exit if trend dies
                pnl = (price - position['entry']) * position['size']
                capital += pnl
                trades.append({'pnl': pnl, 'type': 'SIGNAL'})
                position = None
    
    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['size']
        capital += pnl
        trades.append({'pnl': pnl, 'type': 'OPEN'})
    
    wins = [t for t in trades if t['pnl'] > 0]
    return {
        'name': '4. BREAKOUT CONFIRMADO',
        'trades': len(trades),
        'wins': len(wins),
        'win_rate': len(wins)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades),
        'return_pct': ((capital - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100,
        'capital': capital,
    }

# ═══════════════════════════════════════════════════════════
# ESTRATEGIA 5: MOMENTUM ADAPTATIVA (REFERENCIA)
# ═══════════════════════════════════════════════════════════
def run_momentum(df):
    """La estrategia actual del bot: 4 leyes + momentum 2 velas."""
    capital = INITIAL_CAPITAL
    position = None
    trades = []
    
    for i in range(202, len(df)-1):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        
        if position is None:
            atr = row['ATR'] if not pd.isna(row['ATR']) else 100
            atr_pct = (atr / row['close']) * 100
            high_vol = atr_pct > 0.5
            
            rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
            prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
            prev2_rsi = prev2['RSI'] if not pd.isna(prev2['RSI']) else 50
            adx = row['ADX'] if not pd.isna(row['ADX']) else 0
            
            # Override
            if prev_rsi < 20 and rsi > prev_rsi and adx > 35 and row['close'] > row['open']:
                size = (capital * 0.3) / row['close']
                position = {'entry': row['close'], 'size': size, 'sl': row['close'] - 1.5*atr, 'tp': row['close'] + 3*atr}
                continue
            
            r_thresh = 40 if high_vol else 35
            a_thresh = 15 if high_vol else 20
            m_tol = 0.02 if high_vol else 0.01
            
            marea = row['close'] > row['EMA_200'] * (1 - m_tol)
            fuerza = adx > a_thresh
            ballenas = row['volume'] > row.get('VOL_SMA', 0) * 0.8 if not pd.isna(row.get('VOL_SMA')) else False
            pullback = prev_rsi < r_thresh and rsi > prev_rsi
            momentum = rsi > prev_rsi and prev_rsi > prev2_rsi
            
            if marea and fuerza and ballenas and pullback and momentum:
                size = (capital * 0.3) / row['close']
                position = {'entry': row['close'], 'size': size, 'sl': row['close'] - 1.5*atr, 'tp': row['close'] + 3*atr}
        else:
            price = row['close']
            if price <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['size']
                capital += pnl; trades.append({'pnl': pnl, 'type': 'SL'}); position = None
            elif price >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['size']
                capital += pnl; trades.append({'pnl': pnl, 'type': 'TP'}); position = None
            elif prev['EMA_9'] >= prev['EMA_21'] and row['EMA_9'] < row['EMA_21']:
                pnl = (price - position['entry']) * position['size']
                capital += pnl; trades.append({'pnl': pnl, 'type': 'SIGNAL'}); position = None
    
    if position:
        pnl = (df.iloc[-1]['close'] - position['entry']) * position['size']
        capital += pnl; trades.append({'pnl': pnl, 'type': 'OPEN'})
    
    wins = [t for t in trades if t['pnl'] > 0]
    return {
        'name': '⭐ MOMENTUM ADAPTATIVA (actual)',
        'trades': len(trades),
        'wins': len(wins),
        'win_rate': len(wins)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades),
        'return_pct': ((capital - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100,
        'capital': capital,
    }

# ═══════════════════════════════════════════════════════════
# MULTI-ASSET ROTATION
# ═══════════════════════════════════════════════════════════
async def run_multi_asset(exchange):
    """Rota capital entre BTC, ETH, SOL según momentum."""
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    dfs = {}
    
    for sym in symbols:
        try:
            candles = await exchange.fetch_ohlcv(sym, TIMEFRAME, limit=1000)
            d = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume'])
            d['timestamp'] = pd.to_datetime(d['timestamp'], unit='ms')
            d.set_index('timestamp', inplace=True)
            d = calc_indicators(d)
            dfs[sym] = d
        except Exception as e:
            print(f"   ⚠️ {sym} no disponible: {e}")
    
    if len(dfs) < 2:
        return {
            'name': '5. MULTI-ASSET ROTATION',
            'trades': 0, 'pnl': 0, 'return_pct': 0, 'capital': INITIAL_CAPITAL,
            'note': 'No hay suficientes assets disponibles'
        }
    
    capital = INITIAL_CAPITAL
    current_asset = None
    current_holdings = 0
    trades = []
    rotation_period = 72  # Cada 6 horas (72 × 5min)
    
    min_len = min(len(d) for d in dfs.values())
    
    for i in range(201, min_len, rotation_period):
        # Find best momentum asset
        best_sym = None
        best_mom = -999
        
        for sym, d in dfs.items():
            if i >= len(d):
                continue
            mom = d.iloc[i].get('MOM_10', 0)
            rsi = d.iloc[i].get('RSI', 50)
            if pd.isna(mom): mom = 0
            if pd.isna(rsi): rsi = 50
            
            # Score = momentum + RSI bonus (avoid overbought)
            score = mom - max(0, (rsi - 70) * 0.5)
            if score > best_mom:
                best_mom = score
                best_sym = sym
        
        # Rotate
        if best_sym and best_sym != current_asset:
            # Sell current
            if current_asset and current_holdings > 0:
                sell_price = dfs[current_asset].iloc[i]['close']
                capital = current_holdings * sell_price
                current_holdings = 0
            
            # Buy best
            buy_price = dfs[best_sym].iloc[i]['close']
            current_holdings = capital / buy_price
            capital = 0
            trades.append({'from': current_asset, 'to': best_sym, 'price': buy_price})
            current_asset = best_sym
    
    # Close
    if current_asset and current_holdings > 0:
        final_price = dfs[current_asset].iloc[-1]['close']
        capital = current_holdings * final_price
        current_holdings = 0
    
    return {
        'name': '5. MULTI-ASSET ROTATION',
        'trades': len(trades),
        'pnl': capital - INITIAL_CAPITAL,
        'return_pct': ((capital - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100,
        'capital': capital,
        'rotations': [(t['from'], t['to']) for t in trades[-5:]],
    }

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
async def main():
    print("=" * 70)
    print("🏟️  CT4 LAB — BATTLE ROYALE: 5 Estrategias Nuevas")
    print("=" * 70)
    
    print("\n📥 Descargando datos de BTC...")
    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv('BTC/USDT', TIMEFRAME, limit=1000)
    
    df = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calc_indicators(df)
    
    print(f"✅ {len(df)} velas BTC | {df.index[0].strftime('%m/%d %H:%M')} → {df.index[-1].strftime('%m/%d %H:%M')}")
    print(f"   Rango: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    
    # Run all strategies
    print(f"\n🔬 Ejecutando estrategias...")
    
    r1 = run_grid(df)
    print(f"   ✅ {r1['name']}: {r1['trades']} trades")
    
    r2 = run_dca(df)
    print(f"   ✅ {r2['name']}: {r2['trades']} compras")
    
    r3 = run_mean_reversion(df)
    print(f"   ✅ {r3['name']}: {r3['trades']} trades")
    
    r4 = run_breakout(df)
    print(f"   ✅ {r4['name']}: {r4['trades']} trades")
    
    r5 = run_momentum(df)
    print(f"   ✅ {r5['name']}: {r5['trades']} trades")
    
    print(f"\n📥 Descargando datos multi-asset (ETH, SOL)...")
    r6 = await run_multi_asset(exchange)
    print(f"   ✅ {r6['name']}: {r6['trades']} rotaciones")
    
    await exchange.close()
    
    # ═══ RESULTADOS ═══
    all_results = [r1, r2, r3, r4, r5, r6]
    
    print(f"\n{'='*70}")
    print(f"🏆 RESULTADOS — Battle Royale")
    print(f"   Capital inicial: ${INITIAL_CAPITAL:,}")
    print(f"{'='*70}")
    
    for r in all_results:
        e = "🟢" if r['pnl'] > 0 else ("🔴" if r['pnl'] < 0 else "⚪")
        wr = f"WR:{r.get('win_rate',0):.0f}%" if 'win_rate' in r else ""
        extra = ""
        if 'avg_price' in r:
            extra = f" | AvgPrice: ${r['avg_price']:.0f}"
        if 'buys' in r:
            extra = f" | Buys: {r['buys']} Sells: {r['sells']}"
        if 'rotations' in r:
            extra = f" | Last: {r.get('rotations', [])[-1] if r.get('rotations') else 'N/A'}"
        
        print(f"\n  {e} {r['name']}")
        print(f"     Trades: {r['trades']:>3} | {wr:>7} | PnL: ${r['pnl']:>+10.2f} | Return: {r['return_pct']:>+6.2f}% | Capital: ${r['capital']:>10.2f}{extra}")
    
    # RANKING FINAL
    ranked = sorted(all_results, key=lambda x: x['pnl'], reverse=True)
    
    print(f"\n{'='*70}")
    print("🏆 RANKING FINAL")
    print(f"{'='*70}")
    for i, r in enumerate(ranked):
        medal = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣"][i]
        e = "🟢" if r['pnl'] > 0 else "🔴"
        print(f"  {medal} {e} {r['name']:<40} ${r['pnl']:>+10.2f} ({r['return_pct']:>+6.2f}%)")
    
    print(f"\n{'='*70}")
    print(f"💡 CONCLUSIONES")
    print(f"{'='*70}")
    winner = ranked[0]
    print(f"  🏆 Ganadora: {winner['name']}")
    print(f"  📊 PnL: ${winner['pnl']:+.2f} ({winner['return_pct']:+.2f}%)")
    if ranked[0]['pnl'] > 0 and ranked[-1]['pnl'] < 0:
        print(f"  ⚠️ Diferencia entre mejor y peor: ${ranked[0]['pnl'] - ranked[-1]['pnl']:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
