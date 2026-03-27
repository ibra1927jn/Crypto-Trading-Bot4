"""
V12.1 BACKTEST ENGINE — 6 Month Historical Simulation
Runs on Hetzner, imports actual V12 functions, replays 4H candles.
"""
import paramiko
import time

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

BACKTEST_CODE = r'''
#!/usr/bin/env python3
"""V12.1 Backtest — 6 months of 4H data, full strategy simulation."""
import sys, os, json
os.environ['TG_BOT_TOKEN'] = ''
os.environ['TG_CHAT_ID'] = ''
os.environ['NOHUP'] = '1'
sys.path.insert(0, '/opt/ct4')

import ccxt
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone, timedelta

# Import V12 functions
with open('/opt/ct4/v12_shadow_bot.py', 'r') as f:
    source = f.read()
code_before_main = source.split('async def main_loop')[0]
exec(compile(code_before_main, 'v12_shadow_bot.py', 'exec'), globals())

# ============================================================
# BACKTEST CONFIG
# ============================================================
BACKTEST_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
                  'AVAX/USDT', 'DOGE/USDT', 'XRP/USDT', 'ADA/USDT',
                  'SUI/USDT', 'NEAR/USDT']
INITIAL_CAPITAL = 1000.0
LOOKBACK_DAYS = 180  # 6 months
CANDLE_TF = '4h'

# ============================================================
# DATA DOWNLOAD
# ============================================================
print("=" * 60)
print("V12.1 BACKTEST — 6 Month Historical Simulation")
print("=" * 60)

exchange = ccxt.binance({'enableRateLimit': True})
since = exchange.parse8601(
    (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
)

all_data = {}
for sym in BACKTEST_COINS:
    print(f"  Downloading {sym} ({LOOKBACK_DAYS}d of {CANDLE_TF})...")
    ohlcv = []
    current_since = since
    while True:
        batch = exchange.fetch_ohlcv(sym, CANDLE_TF, since=current_since, limit=1000)
        if not batch:
            break
        ohlcv.extend(batch)
        current_since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    all_data[sym] = df
    print(f"    {len(df)} candles ({df['date'].iloc[0].strftime('%Y-%m-%d')} to "
          f"{df['date'].iloc[-1].strftime('%Y-%m-%d')})")

btc_df = all_data['BTC/USDT'].copy()

# ============================================================
# BTC GRAVITY (per candle)
# ============================================================
btc_df['ema_50'] = ta.ema(btc_df['close'], length=50)
btc_df['rsi_14'] = ta.rsi(btc_df['close'], length=14)
btc_df['btc_bull'] = (btc_df['close'] > btc_df['ema_50']) & (btc_df['rsi_14'] > 45)

# ============================================================
# SIMULATION ENGINE
# ============================================================
print("\n--- Running simulation ---\n")

state = {
    'balance': INITIAL_CAPITAL,
    'positions': {},
    'total_trades': 0,
    'wins': 0,
    'losses': 0,
    'trade_history': [],
    'peak_balance': INITIAL_CAPITAL,
    'daily_start_balance': INITIAL_CAPITAL,
    'daily_start_date': '',
    'kill_switch': False,
    'sl_bans': {},
}

trades_log = []
equity_curve = []
max_positions = 5
kill_days = 0

# Walk through each 4H candle
n_candles = len(btc_df)
warmup = 300  # need 300 candles for EMA200

for i in range(warmup, n_candles - 1):
    btc_row = btc_df.iloc[i]
    btc_is_bullish = bool(btc_row.get('btc_bull', False))
    candle_time = btc_row['date']

    # Kill switch reset at day change
    current_date = candle_time.strftime('%Y-%m-%d')
    if state['daily_start_date'] != current_date:
        state['daily_start_date'] = current_date
        state['daily_start_balance'] = state['balance']
        state['kill_switch'] = False

    if state['kill_switch']:
        kill_days += 1
        equity_curve.append({'time': str(candle_time), 'bal': state['balance']})
        continue

    # Check kill switch
    bal = state['balance']
    daily_start = state.get('daily_start_balance', INITIAL_CAPITAL)
    peak = state.get('peak_balance', INITIAL_CAPITAL)
    if bal > peak:
        state['peak_balance'] = bal
        peak = bal

    if daily_start > 0:
        daily_loss_pct = ((daily_start - bal) / daily_start) * 100
        if daily_loss_pct >= KILL_SWITCH_DAILY_LOSS_PCT:
            state['kill_switch'] = True
            continue
    if peak > 0:
        dd_pct = ((peak - bal) / peak) * 100
        if dd_pct >= KILL_SWITCH_MAX_DD_PCT:
            state['kill_switch'] = True
            continue

    # Manage open positions
    closed_keys = []
    for sym, pos in list(state['positions'].items()):
        sym_df = all_data.get(sym)
        if sym_df is None:
            continue

        # Find matching candle
        mask = sym_df['timestamp'] == btc_row['timestamp']
        if not mask.any():
            continue
        idx = mask.idxmax()
        candle = sym_df.iloc[idx]
        cur_px = candle['close']
        hi = candle['high']
        lo = candle['low']

        # Check SL/TP with high/low of candle (realistic)
        hit_sl = False
        hit_tp = False
        if pos['side'] == 'LONG':
            if lo <= pos['sl']:
                hit_sl = True
                cur_px = pos['sl']  # filled at SL level
            elif hi >= pos['tp']:
                hit_tp = True
                cur_px = pos['tp']
        else:
            if hi >= pos['sl']:
                hit_sl = True
                cur_px = pos['sl']
            elif lo <= pos['tp']:
                hit_tp = True
                cur_px = pos['tp']

        # Trailing stop (use close for trail, not high/low)
        if not hit_sl and not hit_tp:
            close_px = candle['close']
            new_sl, msg = manage_trailing_stop_v12(pos, close_px)
            if pos['sl'] != new_sl:
                pos['sl'] = new_sl

        if hit_sl or hit_tp:
            entry_px = pos['entry_price']
            if pos['side'] == 'LONG':
                pnl = (cur_px - entry_px) * pos['qty']
            else:
                pnl = (entry_px - cur_px) * pos['qty']
            pnl_pct = (pnl / pos['amount']) * 100

            state['balance'] += pos['amount'] + pnl
            state['total_trades'] += 1
            if pnl > 0:
                state['wins'] += 1
            else:
                state['losses'] += 1

            state['trade_history'].append({
                'pnl_pct': round(pnl_pct, 2),
                'side': pos['side'],
                'symbol': sym,
            })
            if len(state['trade_history']) > TRADE_HISTORY_CAP:
                state['trade_history'] = state['trade_history'][-TRADE_HISTORY_CAP:]

            reason = "TP" if hit_tp else "SL"
            trades_log.append({
                'time': str(candle_time),
                'symbol': sym,
                'side': pos['side'],
                'reason': reason,
                'entry': pos['entry_price'],
                'exit': cur_px,
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'balance': round(state['balance'], 2),
            })

            if reason == "SL":
                if 'sl_bans' not in state:
                    state['sl_bans'] = {}
                ban_until = candle_time + timedelta(hours=SL_BAN_HOURS)
                state['sl_bans'][sym] = ban_until.isoformat()

            closed_keys.append(sym)

    for k in closed_keys:
        del state['positions'][k]

    # Scan for new entries
    if len(state['positions']) < max_positions:
        # Kelly
        kelly_risk = RISK_PER_TRADE_PCT
        if len(state['trade_history']) >= KELLY_MIN_TRADES:
            kelly_risk, _ = compute_kelly_risk(state)

        for sym in BACKTEST_COINS:
            if sym in state['positions']:
                continue
            if len(state['positions']) >= max_positions:
                break

            # SL ban check
            bans = state.get('sl_bans', {})
            if sym in bans:
                ban_until = datetime.fromisoformat(bans[sym])
                if candle_time < ban_until:
                    continue
                else:
                    del bans[sym]

            # Sector guard
            sector = classify_sector(sym)
            sector_count = sum(1 for s in state['positions']
                             if classify_sector(s) == sector)
            if sector_count >= MAX_PER_SECTOR:
                continue

            sym_df = all_data.get(sym)
            if sym_df is None:
                continue

            # Get slice up to current candle
            mask = sym_df['timestamp'] <= btc_row['timestamp']
            df_slice = sym_df[mask].copy()
            if len(df_slice) < 250:
                continue

            cur_px = df_slice['close'].iloc[-1]

            # Analyze both sides
            for side in ['LONG', 'SHORT']:
                if sym in state['positions']:
                    break

                ok, rr, sl, tp, reason = analyze_coin_v12(
                    df_slice.copy(), side, btc_is_bullish, cur_px)

                if not ok:
                    continue

                # Position sizing
                amt, qty = calculate_position_size(
                    state['balance'], cur_px, sl, side, risk_pct=kelly_risk)

                if amt <= 0:
                    continue

                state['positions'][sym] = {
                    'side': side,
                    'entry_price': cur_px,
                    'qty': qty,
                    'amount': amt,
                    'sl': sl,
                    'initial_sl': sl,
                    'tp': tp,
                    'trail_stage': 0,
                    'entry_time': candle_time.isoformat(),
                }
                state['balance'] -= amt

    equity_curve.append({'time': str(candle_time), 'bal': round(state['balance'] +
        sum(p['amount'] for p in state['positions'].values()), 2)})

# Close any remaining positions at last price
for sym, pos in list(state['positions'].items()):
    sym_df = all_data.get(sym)
    if sym_df is not None:
        cur_px = sym_df['close'].iloc[-1]
        if pos['side'] == 'LONG':
            pnl = (cur_px - pos['entry_price']) * pos['qty']
        else:
            pnl = (pos['entry_price'] - cur_px) * pos['qty']
        pnl_pct = (pnl / pos['amount']) * 100
        state['balance'] += pos['amount'] + pnl
        state['total_trades'] += 1
        if pnl > 0:
            state['wins'] += 1
        else:
            state['losses'] += 1
        trades_log.append({
            'time': 'END',
            'symbol': sym,
            'side': pos['side'],
            'reason': 'CLOSE',
            'entry': pos['entry_price'],
            'exit': cur_px,
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'balance': round(state['balance'], 2),
        })
state['positions'] = {}

# ============================================================
# RESULTS
# ============================================================
print("\n" + "=" * 60)
print("V12.1 BACKTEST RESULTS — 6 MONTHS")
print("=" * 60)

total = state['total_trades']
wins = state['wins']
losses = total - wins
wr = (wins / total * 100) if total > 0 else 0
final_bal = state['balance']
pnl_total = final_bal - INITIAL_CAPITAL
pnl_pct = (pnl_total / INITIAL_CAPITAL) * 100

# Profit factor
gross_profit = sum(t['pnl'] for t in trades_log if t['pnl'] > 0)
gross_loss = abs(sum(t['pnl'] for t in trades_log if t['pnl'] < 0))
pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

# Max drawdown from equity curve
peak_eq = INITIAL_CAPITAL
max_dd = 0
for pt in equity_curve:
    b = pt['bal']
    if b > peak_eq:
        peak_eq = b
    dd = ((peak_eq - b) / peak_eq) * 100
    if dd > max_dd:
        max_dd = dd

# Average win/loss
avg_win = (sum(t['pnl_pct'] for t in trades_log if t['pnl'] > 0) /
           max(1, wins))
avg_loss = (sum(t['pnl_pct'] for t in trades_log if t['pnl'] <= 0) /
            max(1, losses))

# Trades per month
months = LOOKBACK_DAYS / 30
trades_per_month = total / max(1, months)

print(f"\n  Capital:        ${INITIAL_CAPITAL} -> ${final_bal:.2f}")
print(f"  Total PnL:      ${pnl_total:+.2f} ({pnl_pct:+.1f}%)")
print(f"  Total Trades:   {total} ({trades_per_month:.1f}/month)")
print(f"  Win Rate:       {wr:.1f}% ({wins}W / {losses}L)")
print(f"  Profit Factor:  {pf:.2f}")
print(f"  Avg Win:        {avg_win:+.1f}%")
print(f"  Avg Loss:       {avg_loss:+.1f}%")
print(f"  Max Drawdown:   {max_dd:.1f}%")
print(f"  Kill Switch:    {kill_days} candles paused")
print()

# Verdict
if total == 0:
    verdict = "NO TRADES — Strategy too restrictive"
elif pnl_total > 0 and pf > 1.2 and wr > 40:
    verdict = "PROFITABLE — Strategy shows edge"
elif pnl_total > 0:
    verdict = "MARGINAL — Small profit, needs refinement"
elif max_dd > 20:
    verdict = "DANGEROUS — High drawdown, needs fixes"
else:
    verdict = "UNPROFITABLE — Strategy needs rework"

print(f"  VERDICT: {verdict}")
print()

# Trade details
if trades_log:
    print("  TRADE LOG:")
    print(f"  {'Time':20s} {'Sym':12s} {'Side':6s} {'Rsn':5s} "
          f"{'Entry':>10s} {'Exit':>10s} {'PnL':>8s} {'PnL%':>7s} {'Bal':>10s}")
    print("  " + "-" * 90)
    for t in trades_log:
        print(f"  {t['time'][:19]:20s} {t['symbol']:12s} {t['side']:6s} "
              f"{t['reason']:5s} {t['entry']:10.4f} {t['exit']:10.4f} "
              f"${t['pnl']:+7.2f} {t['pnl_pct']:+6.1f}% ${t['balance']:9.2f}")

print("\n" + "=" * 60)

# Save results as JSON
results = {
    'total_trades': total,
    'wins': wins,
    'losses': losses,
    'win_rate': round(wr, 1),
    'final_balance': round(final_bal, 2),
    'total_pnl': round(pnl_total, 2),
    'total_pnl_pct': round(pnl_pct, 1),
    'profit_factor': round(pf, 2),
    'avg_win_pct': round(avg_win, 1),
    'avg_loss_pct': round(avg_loss, 1),
    'max_drawdown_pct': round(max_dd, 1),
    'trades_per_month': round(trades_per_month, 1),
    'verdict': verdict,
    'trades': trades_log,
}
with open('/opt/ct4/backtest_results.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Results saved to /opt/ct4/backtest_results.json")
'''

print("Uploading backtest engine to Hetzner...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

sftp = ssh.open_sftp()
with sftp.file('/opt/ct4/backtest_v12_6m.py', 'w') as f:
    f.write(BACKTEST_CODE)
sftp.close()

print("Running 6-month backtest (this may take 2-3 minutes)...\n")
_, out, err = ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 venv/bin/python -u backtest_v12_6m.py',
    timeout=300
)
result = out.read().decode("utf-8", errors="replace")
errors = err.read().decode("utf-8", errors="replace")
ssh.close()

with open("backtest_results.txt", "w", encoding="utf-8") as f:
    f.write(result)
    if errors:
        f.write("\n=== STDERR ===\n" + errors)

print(result)
if "Error" in errors or "Traceback" in errors:
    print("\n=== ERRORS ===")
    print(errors[-1500:])
