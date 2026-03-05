"""
CT4 Lab — Flexible Strategy Experiments
========================================
Descarga datos reales de Binance Testnet y prueba 6 variantes
de la estrategia del Francotirador con diferentes niveles de flexibilidad.

Objetivo: Mantener las 4 leyes pero combinar rigidez con flexibilidad.
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt
import pandas as pd
import numpy as np

# ─── CONFIGURACIÓN ─────────────────────────────────────────
SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"
CANDLES = 1000  # ~3.5 días de datos

# ─── INDICADORES ───────────────────────────────────────────
def calculate_indicators(df):
    """Calcula todos los indicadores técnicos."""
    # EMAs
    df['EMA_9'] = df['close'].ewm(span=9).mean()
    df['EMA_21'] = df['close'].ewm(span=21).mean()
    df['EMA_200'] = df['close'].ewm(span=200).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ADX
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    
    plus_dm = high.diff().where(lambda x: (x > 0) & (x > -low.diff()), 0)
    minus_dm = (-low.diff()).where(lambda x: (x > 0) & (x > high.diff()), 0)
    plus_di = 100 * (plus_dm.rolling(14).mean() / df['ATR'])
    minus_di = 100 * (minus_dm.rolling(14).mean() / df['ATR'])
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    df['ADX'] = dx.rolling(14).mean()
    
    # Volume SMA
    df['VOL_SMA'] = df['volume'].rolling(20).mean()
    
    return df

# ─── BACKTESTER ────────────────────────────────────────────
def backtest(df, name, buy_fn, sell_fn, risk_pct=0.30):
    """
    Ejecuta un backtest con reglas de entrada/salida + SL/TP dinámico.
    """
    capital = 10000
    position = None
    trades = []
    
    for i in range(201, len(df)-1):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        if position is None:
            # Check entry
            if buy_fn(row, prev):
                atr = row['ATR'] if not pd.isna(row['ATR']) else 100
                entry = row['close']
                sl = entry - 1.5 * atr
                tp = entry + 3.0 * atr
                size = (capital * risk_pct) / entry
                position = {
                    'entry': entry, 'sl': sl, 'tp': tp,
                    'size': size, 'time': row.name, 'atr': atr
                }
        else:
            price = row['close']
            # Check SL
            if price <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['size']
                capital += pnl
                trades.append({
                    'entry': position['entry'], 'exit': position['sl'],
                    'pnl': pnl, 'pct': (pnl / (position['entry'] * position['size'])) * 100,
                    'type': 'SL', 'duration': i
                })
                position = None
            # Check TP
            elif price >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['size']
                capital += pnl
                trades.append({
                    'entry': position['entry'], 'exit': position['tp'],
                    'pnl': pnl, 'pct': (pnl / (position['entry'] * position['size'])) * 100,
                    'type': 'TP', 'duration': i
                })
                position = None
            # Check signal exit
            elif sell_fn(row, prev):
                pnl = (price - position['entry']) * position['size']
                capital += pnl
                trades.append({
                    'entry': position['entry'], 'exit': price,
                    'pnl': pnl, 'pct': (pnl / (position['entry'] * position['size'])) * 100,
                    'type': 'SIGNAL', 'duration': i
                })
                position = None
    
    # Close open position at last price
    if position:
        price = df.iloc[-1]['close']
        pnl = (price - position['entry']) * position['size']
        capital += pnl
        trades.append({
            'entry': position['entry'], 'exit': price,
            'pnl': pnl, 'pct': (pnl / (position['entry'] * position['size'])) * 100,
            'type': 'OPEN', 'duration': len(df)
        })
    
    # Stats
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    total_pnl = sum(t['pnl'] for t in trades)
    
    return {
        'name': name,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'final_capital': capital,
        'return_pct': ((capital - 10000) / 10000) * 100,
        'trade_list': trades
    }

# ─── ESTRATEGIAS ───────────────────────────────────────────

def strat_1_original(row, prev):
    """Francotirador Original: 4 leyes estrictas"""
    marea = row['close'] > row['EMA_200']
    fuerza = row['ADX'] > 20 if not pd.isna(row['ADX']) else False
    ballenas = row['volume'] > row['VOL_SMA'] if not pd.isna(row['VOL_SMA']) else False
    rsi = prev['RSI'] < 35 and row['RSI'] > prev['RSI'] if not pd.isna(row['RSI']) else False
    return marea and fuerza and ballenas and rsi

def strat_2_marea_flex(row, prev):
    """Marea Flexible: precio dentro del 1% de EMA200"""
    ema200 = row['EMA_200']
    marea = row['close'] > ema200 * 0.99  # 1% tolerance
    fuerza = row['ADX'] > 20 if not pd.isna(row['ADX']) else False
    ballenas = row['volume'] > row['VOL_SMA'] if not pd.isna(row['VOL_SMA']) else False
    rsi = prev['RSI'] < 35 and row['RSI'] > prev['RSI'] if not pd.isna(row['RSI']) else False
    return marea and fuerza and ballenas and rsi

def strat_3_score(row, prev):
    """Sistema de Puntuación: 3.0/4.0 mínimo para comprar"""
    score = 0
    # Marea (0-1): gradual
    dist = (row['close'] - row['EMA_200']) / row['EMA_200']
    if dist > 0.01: score += 1.0
    elif dist > -0.005: score += 0.7
    elif dist > -0.01: score += 0.3
    
    # Fuerza (0-1)
    adx = row['ADX'] if not pd.isna(row['ADX']) else 0
    if adx > 30: score += 1.0
    elif adx > 20: score += 0.7
    elif adx > 15: score += 0.3
    
    # Ballenas (0-1)
    if not pd.isna(row['VOL_SMA']) and row['VOL_SMA'] > 0:
        vol_ratio = row['volume'] / row['VOL_SMA']
        if vol_ratio > 1.5: score += 1.0
        elif vol_ratio > 1.0: score += 0.7
        elif vol_ratio > 0.7: score += 0.3
    
    # Pullback (0-1)
    rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
    prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
    if prev_rsi < 30 and rsi > prev_rsi: score += 1.0
    elif prev_rsi < 35 and rsi > prev_rsi: score += 0.7
    elif prev_rsi < 40 and rsi > prev_rsi: score += 0.5
    
    return score >= 3.0

def strat_4_rsi_override(row, prev):
    """RSI Override: Si RSI < 20, bypass Marea"""
    rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
    prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
    adx = row['ADX'] if not pd.isna(row['ADX']) else 0
    
    # MODO EXTREMO: RSI < 20 + ADX > 40 = comprar sin importar Marea
    if prev_rsi < 20 and rsi > prev_rsi and adx > 40:
        return True
    
    # MODO NORMAL: 4 leyes originales
    marea = row['close'] > row['EMA_200']
    fuerza = adx > 20
    ballenas = row['volume'] > row['VOL_SMA'] if not pd.isna(row['VOL_SMA']) else False
    pullback = prev_rsi < 35 and rsi > prev_rsi
    return marea and fuerza and ballenas and pullback

def strat_5_adaptive(row, prev):
    """Adaptativa: Umbrales cambian según volatilidad (ATR)"""
    atr = row['ATR'] if not pd.isna(row['ATR']) else 100
    price = row['close']
    atr_pct = (atr / price) * 100  # ATR como % del precio
    
    # Alta volatilidad → más flexible | Baja vol → más estricto
    rsi_threshold = 40 if atr_pct > 0.5 else 35 if atr_pct > 0.3 else 30
    adx_threshold = 15 if atr_pct > 0.5 else 20
    marea_tolerance = 0.02 if atr_pct > 0.5 else 0.01 if atr_pct > 0.3 else 0
    
    marea = row['close'] > row['EMA_200'] * (1 - marea_tolerance)
    fuerza = row['ADX'] > adx_threshold if not pd.isna(row['ADX']) else False
    ballenas = row['volume'] > row['VOL_SMA'] * 0.8 if not pd.isna(row['VOL_SMA']) else False
    rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
    prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
    pullback = prev_rsi < rsi_threshold and rsi > prev_rsi
    
    return marea and fuerza and ballenas and pullback

def strat_6_hybrid(row, prev):
    """Híbrido: Score + Override + Adaptive (lo mejor de todo)"""
    rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
    prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
    adx = row['ADX'] if not pd.isna(row['ADX']) else 0
    
    # OVERRIDE: RSI extremo
    if prev_rsi < 20 and rsi > prev_rsi and adx > 40:
        return True
    
    # SCORING con componente adaptativo
    atr = row['ATR'] if not pd.isna(row['ATR']) else 100
    atr_pct = (atr / row['close']) * 100
    tolerance = 0.015 if atr_pct > 0.4 else 0.005
    
    score = 0
    dist = (row['close'] - row['EMA_200']) / row['EMA_200']
    if dist > 0: score += 1.0
    elif dist > -tolerance: score += 0.5
    
    if adx > 25: score += 1.0
    elif adx > 15: score += 0.5
    
    if not pd.isna(row['VOL_SMA']) and row['VOL_SMA'] > 0:
        if row['volume'] > row['VOL_SMA']: score += 1.0
        elif row['volume'] > row['VOL_SMA'] * 0.7: score += 0.5
    
    if prev_rsi < 35 and rsi > prev_rsi: score += 1.0
    elif prev_rsi < 40 and rsi > prev_rsi: score += 0.5
    
    return score >= 2.8

# Exit condition (shared)
def exit_signal(row, prev):
    """Señal de salida: cruce bajista EMA o pérdida de EMA200."""
    cross_down = prev['EMA_9'] >= prev['EMA_21'] and row['EMA_9'] < row['EMA_21']
    lost_macro = row['close'] < row['EMA_200'] * 0.98
    return cross_down or lost_macro

# ─── MAIN ──────────────────────────────────────────────────
async def main():
    print("=" * 65)
    print("🔬 CT4 LAB — Experimentos de Estrategia Flexible")
    print("=" * 65)
    
    # Download data
    print("\n📥 Descargando datos de Binance Testnet...")
    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=CANDLES)
    await exchange.close()
    
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    print(f"✅ {len(df)} velas descargadas")
    print(f"   Periodo: {df.index[0]} → {df.index[-1]}")
    print(f"   Rango: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    
    # Calculate indicators
    df = calculate_indicators(df)
    
    # Run all strategies
    strategies = [
        ("1. ORIGINAL (4 leyes estrictas)", strat_1_original),
        ("2. MAREA FLEXIBLE (tolerancia 1%)", strat_2_marea_flex),
        ("3. SCORE (3.0/4.0 mínimo)", strat_3_score),
        ("4. RSI OVERRIDE (bypass si RSI<20)", strat_4_rsi_override),
        ("5. ADAPTATIVA (umbrales según ATR)", strat_5_adaptive),
        ("6. HÍBRIDO (score+override+adaptive)", strat_6_hybrid),
    ]
    
    results = []
    for name, buy_fn in strategies:
        r = backtest(df, name, buy_fn, exit_signal)
        results.append(r)
    
    # Print results
    print(f"\n{'='*65}")
    print(f"📊 RESULTADOS — {len(df)} velas ({len(df)*5/60:.0f}h de datos)")
    print(f"   Capital inicial: $10,000 | Riesgo: 30% por trade")
    print(f"{'='*65}")
    
    for r in results:
        emoji = "🟢" if r['total_pnl'] > 0 else ("🔴" if r['total_pnl'] < 0 else "⚪")
        print(f"\n{emoji} {r['name']}")
        print(f"   Trades: {r['trades']} | Win Rate: {r['win_rate']:.0f}%")
        print(f"   PnL: ${r['total_pnl']:+.2f} | Capital: ${r['final_capital']:.2f} | Return: {r['return_pct']:+.2f}%")
        if r['trade_list']:
            for t in r['trade_list'][:5]:
                te = "🟢" if t['pnl'] > 0 else "🔴"
                print(f"   {te} ${t['entry']:.0f}→${t['exit']:.0f} | {t['type']} | PnL: ${t['pnl']:+.2f} ({t['pct']:+.1f}%)")
            if len(r['trade_list']) > 5:
                print(f"   ... y {len(r['trade_list'])-5} trades más")
    
    # Final comparison
    print(f"\n{'='*65}")
    print("🏆 RANKING FINAL")
    print(f"{'='*65}")
    sorted_results = sorted(results, key=lambda x: x['total_pnl'], reverse=True)
    for i, r in enumerate(sorted_results):
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"][i]
        emoji = "🟢" if r['total_pnl'] > 0 else ("🔴" if r['total_pnl'] < 0 else "⚪")
        print(f"  {medal} {emoji} {r['name']:<45} {r['trades']:>3} trades | ${r['total_pnl']:>+10.2f} | {r['return_pct']:>+6.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
