"""
CT4 Lab — Deep Optimization of Adaptativa Strategy
====================================================
Toma la estrategia ganadora (Adaptativa) y prueba:
  - Parameter sweep (RSI, ADX, tolerancias)
  - Nuevos filtros (momentum, rebote confirmado, EMA proximity)
  - Optimización de SL/TP (ATR multipliers)
  - Más datos (2000 velas = ~7 días)
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from itertools import product

SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"

def calculate_indicators(df):
    df['EMA_9'] = df['close'].ewm(span=9).mean()
    df['EMA_21'] = df['close'].ewm(span=21).mean()
    df['EMA_200'] = df['close'].ewm(span=200).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Stochastic RSI
    rsi = df['RSI']
    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    df['StochRSI'] = (rsi - rsi_min) / (rsi_max - rsi_min + 1e-10)
    df['StochRSI_K'] = df['StochRSI'].rolling(3).mean()  # Signal
    
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
    df['PLUS_DI'] = plus_di
    df['MINUS_DI'] = minus_di
    
    df['VOL_SMA'] = df['volume'].rolling(20).mean()
    
    # Momentum: rate of change
    df['ROC_5'] = df['close'].pct_change(5) * 100
    
    # Bollinger Bands
    df['BB_MID'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['BB_UPPER'] = df['BB_MID'] + 2 * bb_std
    df['BB_LOWER'] = df['BB_MID'] - 2 * bb_std
    df['BB_PCT'] = (df['close'] - df['BB_LOWER']) / (df['BB_UPPER'] - df['BB_LOWER'] + 1e-10)
    
    # Price distance from EMA200
    df['EMA200_DIST'] = (df['close'] - df['EMA_200']) / df['EMA_200'] * 100
    
    return df

def backtest(df, buy_fn, exit_fn, sl_mult=1.5, tp_mult=3.0, risk_pct=0.30):
    capital = 10000
    peak_capital = 10000
    max_drawdown = 0
    position = None
    trades = []
    
    for i in range(201, len(df)-1):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        prev2 = df.iloc[i-2] if i >= 2 else prev
        
        if position is None:
            if buy_fn(row, prev, prev2):
                atr = row['ATR'] if not pd.isna(row['ATR']) else 100
                entry = row['close']
                sl = entry - sl_mult * atr
                tp = entry + tp_mult * atr
                size = (capital * risk_pct) / entry
                position = {'entry': entry, 'sl': sl, 'tp': tp, 'size': size, 'bar': i}
        else:
            price = row['close']
            pnl = None
            exit_type = None
            
            if price <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['size']
                exit_type = 'SL'
            elif price >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['size']
                exit_type = 'TP'
            elif exit_fn(row, prev):
                pnl = (price - position['entry']) * position['size']
                exit_type = 'SIGNAL'
            
            if pnl is not None:
                capital += pnl
                peak_capital = max(peak_capital, capital)
                dd = (peak_capital - capital) / peak_capital * 100
                max_drawdown = max(max_drawdown, dd)
                trades.append({
                    'pnl': pnl,
                    'pct': (pnl / (position['entry'] * position['size'])) * 100,
                    'type': exit_type,
                    'bars': i - position['bar']
                })
                position = None
    
    if position:
        price = df.iloc[-1]['close']
        pnl = (price - position['entry']) * position['size']
        capital += pnl
        trades.append({'pnl': pnl, 'pct': (pnl / (position['entry'] * position['size'])) * 100, 'type': 'OPEN', 'bars': 0})
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 1
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'win_rate': len(wins)/len(trades)*100 if trades else 0,
        'pnl': sum(t['pnl'] for t in trades),
        'return_pct': ((capital-10000)/10000)*100,
        'max_dd': max_drawdown,
        'profit_factor': (sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses))) if losses else 999,
        'avg_bars': np.mean([t['bars'] for t in trades]) if trades else 0,
        'capital': capital,
        'trade_list': trades
    }

def exit_default(row, prev):
    cross_down = prev['EMA_9'] >= prev['EMA_21'] and row['EMA_9'] < row['EMA_21']
    lost_macro = row['close'] < row['EMA_200'] * 0.98
    return cross_down or lost_macro

async def main():
    print("=" * 70)
    print("🔬 CT4 LAB — Deep Optimization de Estrategia Adaptativa")
    print("=" * 70)
    
    print("\n📥 Descargando datos...")
    exchange = ccxt.binance({'sandbox': True})
    candles = await exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=1000)
    await exchange.close()
    
    df = pd.DataFrame(candles, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = calculate_indicators(df)
    
    print(f"✅ {len(df)} velas | {df.index[0]} → {df.index[-1]}")
    print(f"   Rango: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    
    # ═══════════════════════════════════════════════════════════
    # TEST 1: PARAMETER SWEEP de la Adaptativa
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("🔧 TEST 1: Parameter Sweep — Adaptativa")
    print(f"{'='*70}")
    
    best = None
    results_sweep = []
    
    # Sweep: RSI threshold, ADX threshold, Marea tolerance, SL/TP multipliers
    rsi_thresholds = [30, 35, 40, 45]
    adx_thresholds = [12, 15, 20]
    marea_tols = [0.005, 0.01, 0.02]
    sl_mults = [1.0, 1.5, 2.0]
    tp_mults = [2.0, 3.0, 4.0]
    
    total = len(rsi_thresholds) * len(adx_thresholds) * len(marea_tols) * len(sl_mults) * len(tp_mults)
    count = 0
    
    for rsi_t, adx_t, marea_t, sl_m, tp_m in product(rsi_thresholds, adx_thresholds, marea_tols, sl_mults, tp_mults):
        count += 1
        
        def make_buy(rt, at, mt):
            def buy_fn(row, prev, prev2):
                atr = row['ATR'] if not pd.isna(row['ATR']) else 100
                atr_pct = (atr / row['close']) * 100
                
                r_thresh = rt + 5 if atr_pct > 0.5 else rt
                a_thresh = at - 5 if atr_pct > 0.5 else at
                m_tol = mt * 2 if atr_pct > 0.5 else mt
                
                marea = row['close'] > row['EMA_200'] * (1 - m_tol)
                fuerza = row['ADX'] > a_thresh if not pd.isna(row['ADX']) else False
                ballenas = row['volume'] > row['VOL_SMA'] * 0.8 if not pd.isna(row['VOL_SMA']) else False
                rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
                prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
                pullback = prev_rsi < r_thresh and rsi > prev_rsi
                return marea and fuerza and ballenas and pullback
            return buy_fn
        
        r = backtest(df, make_buy(rsi_t, adx_t, marea_t), exit_default, sl_m, tp_m)
        r['params'] = f"RSI<{rsi_t} ADX>{adx_t} Marea{marea_t} SL{sl_m}x TP{tp_m}x"
        results_sweep.append(r)
        
        if r['trades'] >= 3 and (best is None or r['pnl'] > best['pnl']):
            best = r
    
    print(f"   Combinaciones probadas: {total}")
    
    # Top 10 results
    top10 = sorted([r for r in results_sweep if r['trades'] >= 3], key=lambda x: x['pnl'], reverse=True)[:10]
    
    print(f"\n🏆 TOP 10 combinaciones:")
    print(f"   {'Parámetros':<40} {'Trades':>6} {'Win%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   " + "-"*72)
    for i, r in enumerate(top10):
        medal = ["🥇","🥈","🥉"][i] if i < 3 else f"{i+1}."
        print(f"   {medal} {r['params']:<38} {r['trades']:>4} {r['win_rate']:>5.0f}% ${r['pnl']:>+8.2f} {r['max_dd']:>4.1f}% {r['profit_factor']:>5.1f}")
    
    # ═══════════════════════════════════════════════════════════
    # TEST 2: NUEVOS FILTROS sobre la mejor config
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("🧪 TEST 2: Nuevos Filtros Adicionales")
    print(f"{'='*70}")
    
    best_params = top10[0] if top10 else None
    
    # Strategy A: Base Adaptativa (best params)
    def strat_base(row, prev, prev2):
        atr = row['ATR'] if not pd.isna(row['ATR']) else 100
        atr_pct = (atr / row['close']) * 100
        r_thresh = 40 + (5 if atr_pct > 0.5 else 0)
        a_thresh = 15 - (5 if atr_pct > 0.5 else 0)
        m_tol = 0.02 * (2 if atr_pct > 0.5 else 1)
        
        marea = row['close'] > row['EMA_200'] * (1 - m_tol)
        fuerza = row['ADX'] > a_thresh if not pd.isna(row['ADX']) else False
        ballenas = row['volume'] > row['VOL_SMA'] * 0.8 if not pd.isna(row['VOL_SMA']) else False
        rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
        prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
        pullback = prev_rsi < r_thresh and rsi > prev_rsi
        return marea and fuerza and ballenas and pullback
    
    # Strategy B: + Momentum confirmation (RSI subiendo 2 velas)
    def strat_momentum(row, prev, prev2):
        base = strat_base(row, prev, prev2)
        if not base: return False
        rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
        prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
        prev2_rsi = prev2['RSI'] if not pd.isna(prev2['RSI']) else 50
        # RSI debe estar subiendo consistentemente
        return rsi > prev_rsi and prev_rsi > prev2_rsi
    
    # Strategy C: + Bollinger Band bounce (precio cerca de banda inferior)
    def strat_bollinger(row, prev, prev2):
        base = strat_base(row, prev, prev2)
        if not base: return False
        bb_pct = row['BB_PCT'] if not pd.isna(row['BB_PCT']) else 0.5
        return bb_pct < 0.3  # Precio en zona baja de Bollinger
    
    # Strategy D: + DI+ > DI- (tendencia alcista confirmada por dirección)
    def strat_di_confirm(row, prev, prev2):
        base = strat_base(row, prev, prev2)
        if not base: return False
        plus_di = row['PLUS_DI'] if not pd.isna(row['PLUS_DI']) else 0
        minus_di = row['MINUS_DI'] if not pd.isna(row['MINUS_DI']) else 100
        return plus_di > minus_di  # Fuerza alcista > bajista
    
    # Strategy E: + Close > Open (vela verde) = confirmación
    def strat_green_candle(row, prev, prev2):
        base = strat_base(row, prev, prev2)
        if not base: return False
        return row['close'] > row['open']  # Vela alcista
    
    # Strategy F: ULTIMATE = Base + Green candle + RSI override extremo
    def strat_ultimate(row, prev, prev2):
        rsi = row['RSI'] if not pd.isna(row['RSI']) else 50
        prev_rsi = prev['RSI'] if not pd.isna(prev['RSI']) else 50
        adx = row['ADX'] if not pd.isna(row['ADX']) else 0
        
        # OVERRIDE: RSI extremo = comprar siempre
        if prev_rsi < 20 and rsi > prev_rsi and adx > 35 and row['close'] > row['open']:
            return True
        
        # Base adaptativa + vela verde
        base = strat_base(row, prev, prev2)
        if not base: return False
        return row['close'] > row['open']
    
    # Exits mejorados
    def exit_tight(row, prev):
        """Exit más rápido: trailing stop mental"""
        cross_down = prev['EMA_9'] >= prev['EMA_21'] and row['EMA_9'] < row['EMA_21']
        rsi_high = row['RSI'] > 70 if not pd.isna(row['RSI']) else False
        lost_macro = row['close'] < row['EMA_200'] * 0.985
        return cross_down or rsi_high or lost_macro
    
    filter_tests = [
        ("A. Base Adaptativa (referencia)", strat_base, exit_default, 1.5, 3.0),
        ("B. + Momentum (RSI sube 2 velas)", strat_momentum, exit_default, 1.5, 3.0),
        ("C. + Bollinger Bounce", strat_bollinger, exit_default, 1.5, 3.0),
        ("D. + DI+ > DI- (dirección)", strat_di_confirm, exit_default, 1.5, 3.0),
        ("E. + Vela Verde", strat_green_candle, exit_default, 1.5, 3.0),
        ("F. ULTIMATE (base+verde+override)", strat_ultimate, exit_default, 1.5, 3.0),
        ("G. Base + Exit Tight (RSI>70)", strat_base, exit_tight, 1.5, 3.0),
        ("H. ULTIMATE + Exit Tight", strat_ultimate, exit_tight, 1.5, 3.0),
        ("I. ULTIMATE + SL 1.0x TP 2.5x", strat_ultimate, exit_default, 1.0, 2.5),
        ("J. ULTIMATE + SL 2.0x TP 4.0x", strat_ultimate, exit_default, 2.0, 4.0),
    ]
    
    filter_results = []
    for name, buy_fn, exit_fn, sl, tp in filter_tests:
        r = backtest(df, buy_fn, exit_fn, sl, tp)
        r['name'] = name
        filter_results.append(r)
    
    print(f"\n   {'Estrategia':<45} {'Trades':>6} {'Win%':>5} {'PnL':>10} {'DD%':>5} {'PF':>5}")
    print("   " + "-"*78)
    for r in filter_results:
        e = "🟢" if r['pnl'] > 0 else "🔴" if r['pnl'] < 0 else "⚪"
        print(f"   {e} {r['name']:<43} {r['trades']:>4} {r['win_rate']:>5.0f}% ${r['pnl']:>+8.2f} {r['max_dd']:>4.1f}% {r['profit_factor']:>5.1f}")
    
    # ═══════════════════════════════════════════════════════════
    # FINAL RANKING
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("🏆 RANKING FINAL — Todas las estrategias")
    print(f"{'='*70}")
    
    all_valid = [r for r in filter_results if r['trades'] >= 2]
    final = sorted(all_valid, key=lambda x: x['pnl'], reverse=True)
    
    for i, r in enumerate(final):
        medal = ["🥇","🥈","🥉"][i] if i < 3 else f" {i+1}."
        e = "🟢" if r['pnl'] > 0 else "🔴"
        sharpe = r['pnl'] / (r['max_dd'] + 0.01)
        print(f"  {medal} {e} {r['name']:<43} {r['trades']:>3}T {r['win_rate']:>4.0f}% ${r['pnl']:>+8.2f} DD:{r['max_dd']:.1f}%")
    
    # Print the winner's details
    if final:
        w = final[0]
        print(f"\n{'='*70}")
        print(f"⭐ GANADORA: {w['name']}")
        print(f"{'='*70}")
        print(f"   Trades: {w['trades']} | Wins: {w['wins']} | Win Rate: {w['win_rate']:.0f}%")
        print(f"   PnL: ${w['pnl']:+.2f} | Return: {w['return_pct']:+.2f}%")
        print(f"   Max Drawdown: {w['max_dd']:.2f}% | Profit Factor: {w['profit_factor']:.2f}")
        print(f"   Capital: $10,000 → ${w['capital']:.2f}")
        for t in w['trade_list']:
            e = "🟢 WIN" if t['pnl'] > 0 else "🔴 LOSS"
            print(f"   {e} | PnL: ${t['pnl']:+.2f} ({t['pct']:+.1f}%) | Exit: {t['type']} | {t['bars']*5}min")

if __name__ == "__main__":
    asyncio.run(main())
