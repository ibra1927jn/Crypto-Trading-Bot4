"""
generate_multi_strategy.py — Scoring AI: Multi-Strategy Training Data Generator
================================================================================
Runs THREE different strategy simulations on 12 months of real Binance data
and merges all resulting trades into a single enriched training CSV.

Strategies included:
  1. V11 Sniper (1H) — Aggressive RSI7 + Pullback. Generates many trades.
  2. V12 Original (4H) — Strict EMA21 pullback, conservative.
  3. V14 Radical (4H)  — Relaxed filters, dynamic SL/TP.

The Scoring AI benefits from diversity:
  - If market context X leads to losses across ALL strategies → strong warning
  - Strategy-specific noise gets averaged out automatically

Result: ~2000-3000 labeled trades covering all market regimes.
"""

import paramiko, time, os

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

SCRIPT = r'''#!/usr/bin/env python3
"""Multi-strategy training data generator."""
import sys, os, csv, json
os.environ['TG_BOT_TOKEN'] = ''
sys.path.insert(0, '/opt/ct4')

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
COINS_4H = ['BTC/USDT','ETH/USDT','SOL/USDT','LINK/USDT','AVAX/USDT',
            'DOGE/USDT','XRP/USDT','ADA/USDT','SUI/USDT','NEAR/USDT',
            'PEPE/USDT','WIF/USDT']

OUTPUT   = '/opt/ct4/logs/multi_strategy_training.csv'
MONTHS   = 12

# Strategy configs
V11 = dict(name='V11_Sniper_1H', tf='1h', adx_min=20, rsi_long_max=65,
           rsi_short_min=55, atr_sl=1.0, tp_mult=2.5, rr_min=1.2,
           require_pullback=True, max_hold=48)   # 1H: max 48 candles = 2 days

V12 = dict(name='V12_Original_4H', tf='4h', adx_min=25, rsi_long_max=60,
           rsi_short_min=60, atr_sl=1.5, tp_mult=2.5, rr_min=1.5,
           require_pullback=True, max_hold=42)

V14 = dict(name='V14_Radical_4H', tf='4h', adx_min=20, rsi_long_max=70,
           rsi_short_min=30, atr_sl=1.2, tp_mult=3.0, rr_min=1.2,
           require_pullback=False, max_hold=42)

# ── Download ──────────────────────────────────────────────────────────────────
exchange = ccxt.binance({'enableRateLimit': True})
since    = exchange.parse8601(
    (datetime.now(timezone.utc) - timedelta(days=MONTHS*31)).isoformat()
)

def download(sym, tf):
    ohlcv, cur = [], since
    while True:
        batch = exchange.fetch_ohlcv(sym, tf, since=cur, limit=1000)
        if not batch: break
        ohlcv.extend(batch); cur = batch[-1][0] + 1
        if len(batch) < 1000: break
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df['ema21']   = ta.ema(df['close'], length=21)
    df['ema50']   = ta.ema(df['close'], length=50)
    df['ema200']  = ta.ema(df['close'], length=200)
    df['rsi']     = ta.rsi(df['close'], length=14)
    df['atr']     = ta.atr(df['high'], df['low'], df['close'], length=14)
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx']     = adx_df['ADX_14'] if adx_df is not None else 0
    df['vol_ma']  = df['volume'].rolling(20).mean()
    # v2 enrichment
    bb = ta.bbands(df['close'], length=20, std=2)
    if bb is not None:
        df['bb_upper'] = bb.iloc[:, 0]
        df['bb_lower'] = bb.iloc[:, 2]
    else:
        df['bb_upper'] = df['close'] * 1.02
        df['bb_lower'] = df['close'] * 0.98
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 2] if macd is not None else 0
    df['green'] = (df['close'] > df['open']).astype(int)
    df['streak'] = 0
    streak = 0
    for idx in df.index:
        if df.at[idx, 'green'] == 1:
            streak = max(1, streak + 1)
        else:
            streak = min(-1, streak - 1) if streak <= 0 else -1
        df.at[idx, 'streak'] = streak
    return df

print("Downloading data for all coins and timeframes...", flush=True)

data_4h = {}
data_1h = {}
for sym in COINS_4H:
    data_4h[sym] = download(sym, '4h')
    data_1h[sym] = download(sym, '1h')
    print(f"  {sym} done ({len(data_4h[sym])} 4H / {len(data_1h[sym])} 1H candles)", flush=True)

# Fast lookup dicts
ts4 = {sym: df.set_index('timestamp').to_dict('index') for sym, df in data_4h.items()}
ts1 = {sym: df.set_index('timestamp').to_dict('index') for sym, df in data_1h.items()}

# BTC reference timelines
btc4 = data_4h['BTC/USDT'].copy()
btc1 = data_1h['BTC/USDT'].copy()
btc4['btc_bull'] = (btc4['close'] > btc4['ema50']) & (btc4['rsi'] > 45)
btc4['btc_lat']  = (btc4['rsi'] > 40) & (btc4['rsi'] < 60)
btc1['btc_bull'] = (btc1['close'] > btc1['ema50']) & (btc1['rsi'] > 45)
btc1['btc_lat']  = (btc1['rsi'] > 40) & (btc1['rsi'] < 60)

# ── Entry logic (handles all strategies) ─────────────────────────────────────
def try_entry(row, side, cfg, btc_bull, btc_lat):
    c = row['close']; atr = row['atr']
    if pd.isna(row.get('ema200')) or not atr or atr != atr: return False, 0, 0
    if row['adx'] < cfg['adx_min']: return False, 0, 0

    if side == 'LONG':
        if not btc_bull and not btc_lat: return False, 0, 0
        if row['ema50'] <= row['ema200']: return False, 0, 0
        if cfg['require_pullback']:
            if row['low'] > row['ema21']: return False, 0, 0    # V11/V12: price must touch EMA21
        else:
            if row['rsi'] > cfg['rsi_long_max']: return False, 0, 0  # V14: just not overbought
        sl = c - atr * cfg['atr_sl']
        tp = c + atr * cfg['tp_mult']
    else:
        if row['ema50'] >= row['ema200'] * 1.02: return False, 0, 0
        if cfg['require_pullback']:
            if row['high'] < row['ema21']: return False, 0, 0
        else:
            if row['rsi'] < cfg['rsi_short_min']: return False, 0, 0
        sl = c + atr * cfg['atr_sl']
        tp = c - atr * cfg['tp_mult']

    sl_d = abs(c - sl) / c
    if sl_d < 0.001 or sl_d > 0.20: return False, 0, 0
    if abs(tp - c) / abs(c - sl) < cfg['rr_min']: return False, 0, 0
    return True, sl, tp

def make_vector(row, side, btc_rsi, dt=None):
    c = row['close']
    if not c: return [0]*20
    rsi = float(row.get('rsi') or 50)
    adx = float(row.get('adx') or 25)
    ema50_dist = float(((c - (row.get('ema50') or c)) / c * 100))
    # Bollinger position 0-1
    bb_u = row.get('bb_upper', c*1.02)
    bb_l = row.get('bb_lower', c*0.98)
    bb_range = bb_u - bb_l if bb_u != bb_l else 1
    bb_pos = (c - bb_l) / bb_range
    # MACD hist normalized (-1 to 1)
    mh = float(row.get('macd_hist') or 0)
    macd_norm = max(-1, min(1, mh / max(c * 0.001, 0.0001)))
    # Market regime
    regime = 1.0 if (rsi > 55 and ema50_dist > 0 and adx > 20) else (-1.0 if (rsi < 45 and ema50_dist < 0 and adx > 20) else 0.0)
    hour = dt.hour if dt else 12
    dow = dt.weekday() if dt else 3
    return [
        round(adx, 2),
        round(rsi, 2),
        round(float((row.get('atr') or 0) / c), 5),
        round(ema50_dist, 3),
        round(float(((c - (row.get('ema200') or c)) / c * 100)), 3),
        round(float((btc_rsi or 50) / 100), 4),
        round(float((row.get('volume') or 0) / max(row.get('vol_ma') or 1, 1)), 3),
        1 if side == 'LONG' else -1,
        0.0,  # hold_hours filled on close
        0.0,  # funding_rate (unavailable in backtest)
        0.0,  # oi_change_pct (unavailable in backtest)
        round(hour / 23.0, 3),    # hour normalized
        round(dow / 6.0, 3),      # day normalized
        50.0,                     # fear_greed default (no historical API)
        55.0,                     # btc_dominance default
        regime,                   # market regime
        round(bb_pos, 4),         # bollinger position
        round(macd_norm, 4),      # macd histogram normalized
        round(float(row.get('streak') or 0), 1),  # consecutive candles
        0.0,  # news_sentiment (Phase 3)
    ]

# ── Simulation runner (generic) ───────────────────────────────────────────────
def run_strategy(cfg, btc_df, ts_dict):
    positions, trades = {}, []
    bal = 1000.0
    START = 250

    for i in range(START, len(btc_df) - 1):
        brow = btc_df.iloc[i]
        ts = brow['timestamp']
        dt = brow['date']

        # Close
        for sym in list(positions.keys()):
            p = positions[sym]
            row = ts_dict[sym].get(ts)
            if not row: continue
            h_hours = (dt - p['t']).total_seconds() / 3600
            hsl, htp = False, False
            epx = row['close']
            if p['sd'] == 'LONG':
                if row['low'] <= p['sl']: hsl, epx = True, p['sl']
                elif row['high'] >= p['tp']: htp, epx = True, p['tp']
            else:
                if row['high'] >= p['sl']: hsl, epx = True, p['sl']
                elif row['low'] <= p['tp']: htp, epx = True, p['tp']

            timeout = h_hours >= cfg['max_hold']
            if not hsl and not htp and not timeout:
                # simple trailing
                e, rk = p['e'], abs(p['e'] - p['sl0'])
                if rk > 0:
                    cr = (row['close']-e)/rk if p['sd']=='LONG' else (e-row['close'])/rk
                    if cr >= 1.5 and p.get('ts',0)<2: p['sl']=(e+rk if p['sd']=='LONG' else e-rk); p['ts']=2
                    elif cr >= 0.8 and p.get('ts',0)<1: p['sl']=(e*1.001 if p['sd']=='LONG' else e*0.999); p['ts']=1
                continue

            pnl = (epx-p['e'])*p['q'] if p['sd']=='LONG' else (p['e']-epx)*p['q']
            bal += p['amt'] + pnl
            vec = p['vec']; vec[8] = round(h_hours, 1)
            trades.append({
                'close_time': dt.isoformat(), 'symbol': sym,
                'side': p['sd'], 'strategy': cfg['name'],
                'reason': 'TP' if htp else ('SL' if hsl else 'TIMEOUT'),
                'entry_price': round(p['e'],6), 'exit_price': round(epx,6),
                'amount': round(p['amt'],4), 'pnl': round(pnl,4),
                'pnl_pct': round(pnl/p['amt']*100,4) if p['amt'] else 0,
                'balance': round(bal,2), 'entry_time': p['t'].isoformat(),
                'adx': vec[0], 'rsi': vec[1], 'atr_pct': vec[2],
                'ema50_dist_pct': vec[3], 'ema200_dist_pct': vec[4],
                'btc_corr_4c': vec[5], 'volume_ratio': vec[6],
                'side_int': vec[7], 'hold_hours': vec[8],
                'funding_rate': vec[9], 'oi_change_pct': vec[10],
                'hour_of_day': vec[11], 'day_of_week': vec[12],
                'fear_greed': vec[13], 'btc_dominance': vec[14],
                'market_regime': vec[15], 'bb_position': vec[16],
                'macd_hist_norm': vec[17], 'consec_candles': vec[18],
                'news_sentiment': vec[19],
            })
            del positions[sym]

        # Entry
        if len(positions) < 6:
            for sym in COINS_4H:
                if sym in positions or len(positions) >= 6: continue
                row = ts_dict[sym].get(ts)
                if not row: continue
                for side in ['LONG', 'SHORT']:
                    if sym in positions: break
                    ok, sl, tp = try_entry(row, side, cfg, bool(brow['btc_bull']), bool(brow['btc_lat']))
                    if ok:
                        c = row['close']
                        sl_d = abs(c - sl) / c
                        if sl_d <= 0: continue
                        amt = min(bal * 0.02 / sl_d, bal * 0.25)
                        if amt < 5: continue
                        vec = make_vector(row, side, brow.get('rsi'), dt)
                        positions[sym] = {'sd':side,'e':c,'q':amt/c,'amt':amt,
                                          'sl':sl,'sl0':sl,'tp':tp,'t':dt,'ts':0,'vec':vec}
                        bal -= amt

    # Force close remaining
    for sym, p in positions.items():
        row = ts_dict[sym].get(btc_df.iloc[-1]['timestamp'])
        if not row: continue
        c = row['close']
        pnl = (c-p['e'])*p['q'] if p['sd']=='LONG' else (p['e']-c)*p['q']
        bal += p['amt'] + pnl
        h = (btc_df.iloc[-1]['date']-p['t']).total_seconds()/3600
        vec = p['vec']; vec[8] = round(h,1)
        trades.append({'close_time':btc_df.iloc[-1]['date'].isoformat(),'symbol':sym,
                       'side':p['sd'],'strategy':cfg['name'],'reason':'FORCED_CLOSE',
                       'entry_price':round(p['e'],6),'exit_price':round(c,6),
                       'amount':round(p['amt'],4),'pnl':round(pnl,4),
                       'pnl_pct':round(pnl/p['amt']*100,4)if p['amt'] else 0,
                       'balance':round(bal,2),'entry_time':p['t'].isoformat(),
                       'adx':vec[0],'rsi':vec[1],'atr_pct':vec[2],
                       'ema50_dist_pct':vec[3],'ema200_dist_pct':vec[4],
                       'btc_corr_4c':vec[5],'volume_ratio':vec[6],
                       'side_int':vec[7],'hold_hours':vec[8],
                       'funding_rate':vec[9],'oi_change_pct':vec[10],
                       'hour_of_day':vec[11],'day_of_week':vec[12],
                       'fear_greed':vec[13],'btc_dominance':vec[14],
                       'market_regime':vec[15],'bb_position':vec[16],
                       'macd_hist_norm':vec[17],'consec_candles':vec[18],
                       'news_sentiment':vec[19]})

    wins = sum(1 for t in trades if t['pnl'] > 0)
    print(f"  [{cfg['name']}] {len(trades)} trades | WR={wins/max(1,len(trades))*100:.1f}% | "
          f"PnL=${bal-1000:+.2f}", flush=True)
    return trades

# ── Run all strategies ────────────────────────────────────────────────────────
print("\nRunning simulations...", flush=True)
all_trades = []

all_trades += run_strategy(V14, btc4, ts4)
all_trades += run_strategy(V12, btc4, ts4)
all_trades += run_strategy(V11, btc1, ts1)

# ── Save merged CSV ───────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
if all_trades:
    with open(OUTPUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=all_trades[0].keys())
        w.writeheader(); w.writerows(all_trades)

wins_total  = sum(1 for t in all_trades if t['pnl'] > 0)
total       = len(all_trades)
by_strategy = {}
for t in all_trades:
    s = t['strategy']
    by_strategy.setdefault(s, {'t':0,'w':0})
    by_strategy[s]['t'] += 1
    if t['pnl'] > 0: by_strategy[s]['w'] += 1

print(f"\n{'='*60}")
print(f"  MULTI-STRATEGY TRAINING DATA COMPLETE")
print(f"{'='*60}")
print(f"  Total trades : {total}")
print(f"  Global WR    : {wins_total/max(1,total)*100:.1f}%")
print(f"  Winners      : {wins_total}")
print(f"  Losers       : {total - wins_total}")
print(f"\n  Per strategy:")
for s, v in by_strategy.items():
    wr = v['w']/max(1,v['t'])*100
    print(f"    {s:25s} {v['t']:4d} trades | WR {wr:.1f}%")
print(f"\n  Saved to: {OUTPUT}")
print(f"{'='*60}")
'''

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)
ssh.open_sftp().file('/opt/ct4/generate_multi_strategy.py', 'w').write(SCRIPT)

print("Running multi-strategy generator (up to 6-8 min for 12 months × 3 strategies)...")
_, out, err = ssh.exec_command(
    'cd /opt/ct4 && venv/bin/python -u generate_multi_strategy.py',
    timeout=600
)

# Stream output
for line in out:
    print(line, end='', flush=True)

err_text = err.read().decode()
if err_text.strip():
    print("\n[ERRORS]", err_text[:600])

# Download merged CSV
print("\nDownloading to local scoring_ai folder...")
try:
    local = os.path.join(os.path.dirname(__file__), 'scoring_ai', 'training_data.csv')
    ssh.open_sftp().get('/opt/ct4/logs/multi_strategy_training.csv', local)
    print(f"Saved → {local}")
except Exception as e:
    print(f"[info] Download failed: {e}")

ssh.close()
print("\nNext step:  python scoring_ai/collector.py --csv scoring_ai/training_data.csv")
