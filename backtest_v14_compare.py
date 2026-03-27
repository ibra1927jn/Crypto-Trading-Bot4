"""
V12 vs V14 COMPARATIVE BACKTEST — Radical Filter Elimination
- Tests V12 (original) vs V14 (rigid filters removed)
"""
import paramiko, time

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

BACKTEST_CODE = r'''
#!/usr/bin/env python3
"""V14 Radical Comparative Backtest."""
import sys, os, json
os.environ['TG_BOT_TOKEN'] = ''
os.environ['TG_CHAT_ID'] = ''
os.environ['NOHUP'] = '1'
sys.path.insert(0, '/opt/ct4')

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timezone, timedelta

# ============================================================
# STRATEGY CONFIGS
# ============================================================
V12_CONFIG = {
    'name': 'V12 (Original)',
    'adx_min': 25,
    'require_ema21_pullback': True,  # Rigid distance < 3%
    'atr_sl_multiplier': 1.5,        # Very wide SL
    'tp_multiplier': 2.5,
    'dynamic_tp': False,
    'rr_min_4h': 1.5,
    'btc_lateral_allowed': False,
    'trail_be_threshold': 1.0,
    'trail_lock_threshold': 2.0,
    'kill_daily': 5.0,
    'kill_dd': 15.0,
    'max_hold_candles': 999,
}

V14_CONFIG = {
    'name': 'V14 (Radical)',
    'adx_min': 20,                   # Only baseline trend strength
    'require_ema21_pullback': False, # ELIMINATED: entering on structure, not exact EMA proximity
    'atr_sl_multiplier': 1.2,        # Tighter SL -> easier to get good R/R
    'tp_multiplier': 3.0,            # Aiming for bigger wins
    'dynamic_tp': True,              # TP = Entry + ATR * 3.0
    'rr_min_4h': 1.2,                # Lower R/R barrier
    'btc_lateral_allowed': True,     # Allowed to trade on BTC lateral
    'trail_be_threshold': 0.8,       # Breakeven faster
    'trail_lock_threshold': 1.5,     # Lock profits faster
    'kill_daily': 8.0,
    'kill_dd': 20.0,
    'max_hold_candles': 42,          # Force close after 1 week (42 * 4H = 7 days) if no TP/SL
}

# ============================================================
# DATA DOWNLOAD
# ============================================================
BACKTEST_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
                  'AVAX/USDT', 'DOGE/USDT', 'XRP/USDT', 'ADA/USDT',
                  'SUI/USDT', 'NEAR/USDT', 'PEPE/USDT', 'WIF/USDT']
INITIAL_CAPITAL = 1000.0
LOOKBACK_DAYS = 180
CANDLE_TF = '4h'

exchange = ccxt.binance({'enableRateLimit': True})
since = exchange.parse8601(
    (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
)

all_data = {}
print("Downloading data...")
for sym in BACKTEST_COINS:
    ohlcv = []
    current_since = since
    while True:
        batch = exchange.fetch_ohlcv(sym, CANDLE_TF, since=current_since, limit=1000)
        if not batch: break
        ohlcv.extend(batch)
        current_since = batch[-1][0] + 1
        if len(batch) < 1000: break
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    all_data[sym] = df

btc_df = all_data['BTC/USDT'].copy()
btc_df['ema_50'] = ta.ema(btc_df['close'], length=50)
btc_df['rsi_14'] = ta.rsi(btc_df['close'], length=14)
btc_df['btc_bull'] = (btc_df['close'] > btc_df['ema_50']) & (btc_df['rsi_14'] > 45)
btc_df['btc_lateral'] = (btc_df['rsi_14'] > 40) & (btc_df['rsi_14'] < 60)
mid_idx = len(btc_df) // 2

# ============================================================
# ANALYSIS ENGINE 
# ============================================================
def analyze_coin(df, side, btc_is_bullish, btc_is_lateral, cur_px, cfg):
    if len(df) < 250: return False, 0, 0, 0, "No data"

    df['ema_21'] = ta.ema(df['close'], length=21)
    df['ema_50'] = ta.ema(df['close'], length=50)
    df['ema_200'] = ta.ema(df['close'], length=200)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx'] = adx_df['ADX_14'] if adx_df is not None else 0
    df['rsi_14'] = ta.rsi(df['close'], length=14)

    last = df.iloc[-1]
    ema21, ema50, ema200, atr, adx, rsi = (
        last['ema_21'], last['ema_50'], last['ema_200'], 
        last['atr'], last['adx'], last['rsi_14']
    )

    if pd.isna(ema200) or pd.isna(atr) or atr == 0:
        return False, 0, 0, 0, "NaN"

    if side == 'LONG':
        if not btc_is_bullish and not (cfg['btc_lateral_allowed'] and btc_is_lateral):
            return False, 0, 0, 0, "BTC Bearish"
            
        if adx < cfg['adx_min']: return False, 0, 0, 0, "ADX Low"
        if not (ema50 > ema200): return False, 0, 0, 0, "No macro trend"
        
        if cfg['require_ema21_pullback']:
            dist_pct = abs(cur_px - ema21) / cur_px * 100
            if dist_pct > 3.0 or cur_px < ema21 * 0.97:
                return False, 0, 0, 0, "No pullback EMA21"

        if not cfg['require_ema21_pullback']:
            # Replace pullback with a simple "not extremely overbought" check
            if rsi > 70: return False, 0, 0, 0, "RSI > 70 (Overbought)"

        # SL / TP
        recent_low = df['low'].iloc[-10:].min()
        calculated_sl = cur_px - atr * cfg['atr_sl_multiplier']
        sl = min(recent_low, calculated_sl) if cfg['require_ema21_pullback'] else calculated_sl
        
        if cfg['dynamic_tp']:
            tp = cur_px + atr * cfg['tp_multiplier']
        else:
            tp = cur_px + (cur_px - sl) * cfg['tp_multiplier']

        sl_dist = (cur_px - sl) / cur_px
        if sl_dist < 0.001 or sl_dist > (0.08 if cfg['require_ema21_pullback'] else 0.15):
            return False, 0, 0, 0, "SL invalid"

        rr = (tp - cur_px) / (cur_px - sl)
        if rr < cfg['rr_min_4h']: return False, 0, 0, 0, f"R/R < {cfg['rr_min_4h']}"

        return True, rr, sl, tp, "OK"

    else:  # SHORT
        if ema50 > ema200 * 1.02: return False, 0, 0, 0, "No macro bear"
        if adx < cfg['adx_min']: return False, 0, 0, 0, "ADX Low"

        if cfg['require_ema21_pullback']:
            dist_pct = abs(cur_px - ema21) / cur_px * 100
            if dist_pct > 3.0 or cur_px > ema21 * 1.03:
                return False, 0, 0, 0, "No pullback EMA21"
                
        if not cfg['require_ema21_pullback']:
            if rsi < 30: return False, 0, 0, 0, "RSI < 30 (Oversold)"

        # SL / TP
        recent_high = df['high'].iloc[-10:].max()
        calculated_sl = cur_px + atr * cfg['atr_sl_multiplier']
        sl = max(recent_high, calculated_sl) if cfg['require_ema21_pullback'] else calculated_sl
        
        if cfg['dynamic_tp']:
            tp = cur_px - atr * cfg['tp_multiplier']
        else:
            tp = cur_px - (sl - cur_px) * cfg['tp_multiplier']

        sl_dist = (sl - cur_px) / cur_px
        if sl_dist < 0.001 or sl_dist > (0.08 if cfg['require_ema21_pullback'] else 0.15):
            return False, 0, 0, 0, "SL invalid"

        rr = (cur_px - tp) / (sl - cur_px)
        if rr < cfg['rr_min_4h']: return False, 0, 0, 0, f"R/R < {cfg['rr_min_4h']}"

        return True, rr, sl, tp, "OK"

def trailing_stop(pos, cur_px, cfg):
    entry = pos['entry_price']
    risk = abs(entry - pos['initial_sl'])
    if risk == 0: return pos['sl'], "Hold"

    current_r = (cur_px - entry)/risk if pos['side'] == 'LONG' else (entry - cur_px)/risk

    if current_r >= cfg['trail_lock_threshold'] and pos.get('trail_stage', 0) < 2:
        new_sl = entry + risk*1.0 if pos['side'] == 'LONG' else entry - risk*1.0
        pos['trail_stage'] = 2
        return new_sl, "Lock +1R"
    elif current_r >= cfg['trail_be_threshold'] and pos.get('trail_stage', 0) < 1:
        new_sl = entry*1.001 if pos['side'] == 'LONG' else entry*0.999
        pos['trail_stage'] = 1
        return new_sl, "Breakeven"
    return pos['sl'], "Hold"

# ============================================================
# RUNNER
# ============================================================
def run_simulation(cfg, start_idx, end_idx, label):
    state = {'balance': INITIAL_CAPITAL, 'positions': {}, 'total_trades': 0, 'wins': 0}
    trades_log = []
    equity_curve = []
    
    for i in range(start_idx, end_idx):
        btc_row = btc_df.iloc[i]
        candle_time = btc_row['date']

        closed_keys = []
        for sym, pos in list(state['positions'].items()):
            sym_df = all_data.get(sym)
            if sym_df is None: continue
            
            mask = sym_df['timestamp'] == btc_row['timestamp']
            if not mask.any(): continue
            candle = sym_df.iloc[mask.idxmax()]
            cur_px, hi, lo = candle['close'], candle['high'], candle['low']

            # Max hold (timeout)
            entry_time = datetime.fromisoformat(pos['entry_time'])
            if (candle_time - entry_time).total_seconds() / (4 * 3600) >= cfg['max_hold_candles']:
                pnl = (cur_px - pos['entry_price']) * pos['qty'] if pos['side'] == 'LONG' else (pos['entry_price'] - cur_px) * pos['qty']
                state['balance'] += pos['amount'] + pnl
                state['total_trades'] += 1
                if pnl > 0: state['wins'] += 1
                trades_log.append({'time': str(candle_time)[:10], 'symbol': sym, 'side': pos['side'], 
                                   'reason': 'TIMEOUT', 'entry': pos['entry_price'], 'exit': cur_px, 
                                   'pnl': pnl, 'pnl_pct': pnl/pos['amount']*100, 'bal': state['balance']})
                closed_keys.append(sym)
                continue

            hit_sl, hit_tp, exit_px = False, False, cur_px
            if pos['side'] == 'LONG':
                if lo <= pos['sl']: hit_sl, exit_px = True, pos['sl']
                elif hi >= pos['tp']: hit_tp, exit_px = True, pos['tp']
            else:
                if hi >= pos['sl']: hit_sl, exit_px = True, pos['sl']
                elif lo <= pos['tp']: hit_tp, exit_px = True, pos['tp']

            if not hit_sl and not hit_tp:
                new_sl, _ = trailing_stop(pos, cur_px, cfg)
                if pos['sl'] != new_sl: pos['sl'] = new_sl

            if hit_sl or hit_tp:
                pnl = (exit_px - pos['entry_price']) * pos['qty'] if pos['side'] == 'LONG' else (pos['entry_price'] - exit_px) * pos['qty']
                state['balance'] += pos['amount'] + pnl
                state['total_trades'] += 1
                if pnl > 0: state['wins'] += 1
                trades_log.append({'time': str(candle_time)[:10], 'symbol': sym, 'side': pos['side'], 
                                   'reason': "TP" if hit_tp else "SL", 'entry': pos['entry_price'], 'exit': exit_px, 
                                   'pnl': pnl, 'pnl_pct': pnl/pos['amount']*100, 'bal': state['balance']})
                closed_keys.append(sym)

        for k in closed_keys: del state['positions'][k]

        if len(state['positions']) < 5:
            for sym in BACKTEST_COINS:
                if sym in state['positions'] or len(state['positions']) >= 5: continue
                sym_df = all_data.get(sym)
                if sym_df is None: continue
                mask = sym_df['timestamp'] <= btc_row['timestamp']
                df_slice = sym_df[mask].copy()
                if len(df_slice) < 250: continue

                for side in ['LONG', 'SHORT']:
                    if sym in state['positions']: break
                    cur_px = df_slice['close'].iloc[-1]
                    ok, rr, sl, tp, _ = analyze_coin(df_slice.copy(), side, bool(btc_row.get('btc_bull')), bool(btc_row.get('btc_lateral')), cur_px, cfg)
                    if ok:
                        amt = state['balance'] * 0.02 / abs(cur_px - sl) * cur_px
                        if 5 <= amt <= state['balance'] * 0.25:
                            state['positions'][sym] = {'side': side, 'entry_price': cur_px, 'qty': amt/cur_px, 'amount': amt, 
                                                       'sl': sl, 'initial_sl': sl, 'tp': tp, 'entry_time': candle_time.isoformat()}
                            state['balance'] -= amt

        total_eq = state['balance'] + sum(p['amount'] for p in state['positions'].values())
        equity_curve.append(total_eq)

    # Close remaining
    for sym, pos in state['positions'].items():
        cur_px = all_data[sym]['close'].iloc[-1]
        pnl = (cur_px - pos['entry_price']) * pos['qty'] if pos['side'] == 'LONG' else (pos['entry_price'] - cur_px) * pos['qty']
        state['balance'] += pos['amount'] + pnl
        state['total_trades'] += 1
        if pnl > 0: state['wins'] += 1

    pf = (sum(t['pnl'] for t in trades_log if t['pnl']>0) / abs(sum(t['pnl'] for t in trades_log if t['pnl']<0))) if any(t['pnl']<0 for t in trades_log) else 99.0
    max_dd = 0
    peak = INITIAL_CAPITAL
    for b in equity_curve:
        if b > peak: peak = b
        if peak > 0 and (peak - b)/peak > max_dd: max_dd = (peak - b)/peak
        
    return {
        'config': cfg['name'], 'label': label, 'trades': state['total_trades'],
        'wr': state['wins']/state['total_trades']*100 if state['total_trades']>0 else 0,
        'pnl$': state['balance'] - INITIAL_CAPITAL, 'pnl%': (state['balance'] - INITIAL_CAPITAL)/INITIAL_CAPITAL*100,
        'pf': pf, 'mdd': max_dd * 100
    }

print("Running...")
r = []
for c in [V12_CONFIG, V14_CONFIG]:
    r.append(run_simulation(c, 260, len(btc_df)-1, 'FULL 6M'))
    r.append(run_simulation(c, 260, mid_idx, 'IN-SAMPLE'))
    r.append(run_simulation(c, mid_idx, len(btc_df)-1, 'BLIND TEST'))

print("\n" + "="*80)
print(f"{'Config':16s} {'Period':12s} {'Trades':>6s} {'WR':>6s} {'PnL$':>8s} {'PnL%':>7s} {'PF':>5s} {'MDD':>5s}")
for x in r:
    print(f"{x['config']:16s} {x['label']:12s} {x['trades']:6d} {x['wr']:5.1f}% ${x['pnl$']:+7.2f} {x['pnl%']:+6.1f}% {x['pf']:5.2f} {x['mdd']:5.1f}%")
print("="*80)
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)
ssh.open_sftp().file('/opt/ct4/backtest_v14_radical.py', 'w').write(BACKTEST_CODE)

print("Running V14 backtest...")
_, out, _ = ssh.exec_command('cd /opt/ct4 && NOHUP=1 venv/bin/python -u backtest_v14_radical.py', timeout=600)
print(out.read().decode())
ssh.close()
