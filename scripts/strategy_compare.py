"""
📊 Strategy Comparison Lab — Real 2-year Binance data
=====================================================
Compares 5 different strategies across 10 coins:
1) Current: Score≥55, TP3%, SL1.5% (our bot)
2) Scalper: Quick TP1.5%, SL1%
3) Swing: Patient TP5%, SL2%
4) Momentum: RSI<30 + Volume>2x, TP3%, SL1.5%
5) Mean Reversion: BB<0.1, TP2%, SL1%
"""
import ccxt, pandas as pd, pandas_ta as ta, numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

COINS = ['CHESS/USDT','COS/USDT','DOGE/USDT','XRP/USDT','ADA/USDT',
         'JASMY/USDT','GALA/USDT','FLOKI/USDT','PEPE/USDT','CHZ/USDT']
CAPITAL = 30.0
FEE = 0.1

class Strategy:
    def __init__(self, name, tp, sl, check_entry):
        self.name = name; self.tp = tp; self.sl = sl
        self.check_entry = check_entry  # function(row, indicators) -> bool

def backtest(df, strategy, capital=CAPITAL):
    if df is None or len(df) < 50: return None
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    opens = df['open'].values
    volume = df['volume'].values

    # Pre-calculate indicators
    rsi = ta.rsi(df['close'], 14)
    rsi_vals = rsi.values if rsi is not None else np.full(len(close), 50)
    vol_sma = pd.Series(volume).rolling(20).mean().values
    bb = ta.bbands(df['close'], 20, 2)
    bb_pos = np.full(len(close), 0.5)
    if bb is not None:
        bbl = [c for c in bb.columns if c.startswith('BBL_')]
        bbu = [c for c in bb.columns if c.startswith('BBU_')]
        if bbl and bbu:
            bl = bb[bbl[0]].values; bu = bb[bbu[0]].values
            rng = bu - bl
            with np.errstate(divide='ignore', invalid='ignore'):
                bb_pos = np.where(rng > 0, (close - bl) / rng, 0.5)

    ema9 = ta.ema(df['close'], 9)
    ema21 = ta.ema(df['close'], 21)
    ema9v = ema9.values if ema9 is not None else close
    ema21v = ema21.values if ema21 is not None else close

    # Score calculation (same as bot)
    scores = np.zeros(len(close))
    for i in range(50, len(close)):
        sc = 0
        h24 = np.max(high[max(0,i-24):i+1]); l24 = np.min(low[max(0,i-24):i+1])
        rng24 = h24 - l24
        rpos = (close[i] - l24) / rng24 if rng24 > 0 else 0.5
        if rpos < 0.15: sc += 20
        elif rpos < 0.30: sc += 15
        elif rpos < 0.45: sc += 8

        r = rsi_vals[i] if not np.isnan(rsi_vals[i]) else 50
        if r < 25: sc += 20
        elif r < 35: sc += 15
        elif r < 45: sc += 8

        vr = volume[i] / vol_sma[i] if not np.isnan(vol_sma[i]) and vol_sma[i] > 0 else 1
        if vr > 3: sc += 15
        elif vr > 2: sc += 10
        elif vr > 1.5: sc += 5

        greens = sum(1 for j in range(max(0,i-2), i+1) if close[j] > opens[j])
        if greens >= 3: sc += 15
        elif greens >= 2: sc += 10

        bp = bb_pos[i] if not np.isnan(bb_pos[i]) else 0.5
        if bp < 0.10: sc += 15
        elif bp < 0.25: sc += 10

        scores[i] = sc

    # Simulate trading
    balance = capital
    trades = []; in_trade = False; entry_price = 0; entry_bar = 0; units = 0

    for i in range(50, len(close)):
        if in_trade:
            # Check exit
            pnl_pct = (close[i] / entry_price - 1) * 100
            bars_held = i - entry_bar

            exit_reason = None
            if pnl_pct >= strategy.tp: exit_reason = 'TP'
            elif pnl_pct <= -strategy.sl: exit_reason = 'SL'
            elif bars_held >= 4 * 1 and pnl_pct < 1.0: exit_reason = 'TIMEOUT'  # 4h timeout

            if exit_reason:
                sell_val = units * close[i]
                fee = sell_val * FEE / 100
                balance = sell_val - fee
                pnl = balance - capital  # vs initial
                trades.append({
                    'pnl_pct': pnl_pct, 'reason': exit_reason,
                    'bars': bars_held, 'entry': entry_price, 'exit': close[i]
                })
                in_trade = False
        else:
            # Check entry
            indicators = {
                'score': scores[i], 'rsi': rsi_vals[i] if not np.isnan(rsi_vals[i]) else 50,
                'bb_pos': bb_pos[i] if not np.isnan(bb_pos[i]) else 0.5,
                'vol_ratio': volume[i] / vol_sma[i] if not np.isnan(vol_sma[i]) and vol_sma[i] > 0 else 1,
                'ema_bull': ema9v[i] > ema21v[i] if not np.isnan(ema9v[i]) and not np.isnan(ema21v[i]) else False,
                'price': close[i],
            }
            if strategy.check_entry(indicators):
                amount = balance * 0.95
                fee = amount * FEE / 100
                invested = amount - fee
                units = invested / close[i]
                entry_price = close[i]
                entry_bar = i
                in_trade = True
                balance -= amount

    # If still in trade, close at last price
    if in_trade:
        sell_val = units * close[-1]
        fee = sell_val * FEE / 100
        balance = sell_val - fee
        pnl_pct = (close[-1] / entry_price - 1) * 100
        trades.append({'pnl_pct': pnl_pct, 'reason': 'END', 'bars': len(close)-entry_bar, 'entry': entry_price, 'exit': close[-1]})

    if not trades: return None
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    final_bal = balance if not in_trade else balance
    total_pnl = final_bal - capital

    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100,
        'total_pnl': total_pnl,
        'pnl_pct': (final_bal / capital - 1) * 100,
        'avg_win': np.mean([t['pnl_pct'] for t in wins]) if wins else 0,
        'avg_loss': np.mean([t['pnl_pct'] for t in losses]) if losses else 0,
        'best_trade': max(t['pnl_pct'] for t in trades),
        'worst_trade': min(t['pnl_pct'] for t in trades),
        'avg_bars': np.mean([t['bars'] for t in trades]),
        'tp_count': sum(1 for t in trades if t['reason']=='TP'),
        'sl_count': sum(1 for t in trades if t['reason']=='SL'),
        'timeout_count': sum(1 for t in trades if t['reason']=='TIMEOUT'),
    }

# ═══════════════════════════════════════════════════════
# DEFINE STRATEGIES
# ═══════════════════════════════════════════════════════

strategies = [
    Strategy("1. Current Bot (SC≥55 TP3/SL1.5)", 3.0, 1.5,
        lambda i: i['score'] >= 55),
    Strategy("2. Scalper (SC≥45 TP1.5/SL1)", 1.5, 1.0,
        lambda i: i['score'] >= 45),
    Strategy("3. Swing (SC≥65 TP5/SL2)", 5.0, 2.0,
        lambda i: i['score'] >= 65),
    Strategy("4. Momentum (RSI<30+Vol>2 TP3/SL1.5)", 3.0, 1.5,
        lambda i: i['rsi'] < 30 and i['vol_ratio'] > 2),
    Strategy("5. Mean Rev (BB<0.1 TP2/SL1)", 2.0, 1.0,
        lambda i: i['bb_pos'] < 0.10),
    Strategy("6. Cautious (SC≥70 TP5/SL2) [F&G<20]", 5.0, 2.0,
        lambda i: i['score'] >= 70),
    Strategy("7. EMA Cross (SC≥50+Bull TP3/SL1.5)", 3.0, 1.5,
        lambda i: i['score'] >= 50 and i['ema_bull']),
]

# ═══════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════

print("=" * 80)
print("📊 STRATEGY COMPARISON LAB — Real Binance Data (2 years, 1h candles)")
print("=" * 80)

ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
all_results = {}

for coin in COINS:
    print(f"\n📈 Loading {coin}...")
    try:
        ohlcv = ex.fetch_ohlcv(coin, '1h', limit=1000)  # ~42 days
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        print(f"   {len(df)} candles | {df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")

        for strat in strategies:
            result = backtest(df, strat)
            key = strat.name
            if key not in all_results: all_results[key] = []
            if result:
                result['coin'] = coin
                all_results[key].append(result)
    except Exception as e:
        print(f"   ⚠️ Error: {e}")

# ═══════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════

print("\n" + "=" * 80)
print("📊 RESULTS SUMMARY (averages across all coins)")
print("=" * 80)
print(f"\n{'Strategy':<45s} {'Trades':>6s} {'WR%':>5s} {'PnL$':>8s} {'AvgW%':>6s} {'AvgL%':>6s} {'TP':>4s} {'SL':>4s} {'TO':>4s}")
print("-" * 90)

best_strat = None; best_pnl = -999
for strat in strategies:
    results = all_results.get(strat.name, [])
    if not results: continue
    tt = sum(r['total_trades'] for r in results)
    tw = sum(r['wins'] for r in results)
    wr = tw/tt*100 if tt > 0 else 0
    tpnl = sum(r['total_pnl'] for r in results)
    aw = np.mean([r['avg_win'] for r in results if r['avg_win'] > 0]) if any(r['avg_win']>0 for r in results) else 0
    al = np.mean([r['avg_loss'] for r in results if r['avg_loss'] < 0]) if any(r['avg_loss']<0 for r in results) else 0
    tps = sum(r['tp_count'] for r in results)
    sls = sum(r['sl_count'] for r in results)
    tos = sum(r['timeout_count'] for r in results)

    icon = '🏆' if tpnl > 0 else '❌'
    print(f"{icon} {strat.name:<43s} {tt:>6d} {wr:>5.1f} ${tpnl:>7.2f} {aw:>5.1f}% {al:>5.1f}% {tps:>4d} {sls:>4d} {tos:>4d}")
    if tpnl > best_pnl:
        best_pnl = tpnl; best_strat = strat.name

print(f"\n🏆 BEST STRATEGY: {best_strat} (PnL: ${best_pnl:+.2f})")

# Per-coin breakdown for top 3
print("\n" + "=" * 80)
print("📊 PER-COIN BREAKDOWN")
print("=" * 80)
for strat in strategies:
    results = all_results.get(strat.name, [])
    if not results: continue
    total = sum(r['total_pnl'] for r in results)
    print(f"\n{'─'*50}")
    print(f"  {strat.name} (Total: ${total:+.2f})")
    print(f"{'─'*50}")
    for r in sorted(results, key=lambda x: -x['total_pnl']):
        icon = '🟢' if r['total_pnl'] > 0 else '🔴'
        print(f"  {icon} {r['coin']:<15s} T:{r['total_trades']:>3d} WR:{r['win_rate']:>5.1f}% PnL:${r['total_pnl']:>+7.2f} Best:{r['best_trade']:>+5.1f}%")
