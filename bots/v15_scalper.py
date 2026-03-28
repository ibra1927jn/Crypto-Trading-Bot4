#!/usr/bin/env python3
"""
v15_scalper.py — Fast 15-Minute Scalper Bot
============================================
Independent from v12_shadow_bot.py. Runs on its own state/log files.

Strategy: RSI7 Mean-Reversion Scalper on 15m candles
  • LONG when RSI7 < 25 AND candle closes above EMA9 (bounce confirmed)
  • SHORT when RSI7 > 75 AND candle closes below EMA9 (rejection confirmed)
  • TP: 1.5x ATR from entry  |  SL: 1.0x ATR from entry
  • Max hold: 24 candles (6 hours) — forces close if no TP/SL
  • Trailing: breakeven at +0.5R, lock +0.5R at +1.0R
  • Max 3 simultaneous positions
  • Kill switch: 3% daily loss → pause until midnight UTC

Targets: 10-30 trades/day across 12 coins
Paper trading mode only (simulated fills on close price).
"""

import os
import sys
import json
import csv
import logging
import asyncio
from datetime import datetime, timezone, timedelta

import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta

# ==========================================
# CONFIG
# ==========================================
TG_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT  = os.getenv('TG_CHAT_ID')

CAPITAL         = 1000.0
MAX_POSITIONS   = 5
RISK_PER_TRADE  = 0.01       # 1% risk per trade (more trades, smaller size)
MAX_POS_PCT     = 0.15       # max 15% of equity per trade
SCAN_INTERVAL   = 30         # seconds between scans

# SL/TP
ATR_SL_MULT     = 1.0        # tight SL: 1x ATR
ATR_TP_MULT     = 1.5        # TP: 1.5x ATR (R/R = 1.5)
MAX_HOLD_CANDLES= 24         # 24 × 15m = 6 hours max

# RSI7 Thresholds (relaxed for high frequency)
RSI_LONG_ENTRY  = 35         # RSI7 < 35 = oversold zone → buy
RSI_SHORT_ENTRY = 65         # RSI7 > 65 = overbought zone → sell
RSI_PERIOD      = 7          # fast RSI

# Kill Switch
KILL_DAILY_LOSS = 3.0        # % daily loss → stop trading

# Trailing Stop
TRAIL_BE_R      = 0.5        # move SL to breakeven at +0.5R
TRAIL_LOCK_R    = 1.0        # lock +0.5R profit at +1.0R

# COINS: top liquid coins for scalping
COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT',
         'DOGE/USDT', 'AVAX/USDT', 'LINK/USDT', 'ADA/USDT',
         'SUI/USDT', 'NEAR/USDT', 'PEPE/USDT', 'WIF/USDT']

STATE_FILE = "/opt/ct4/state/v15_scalper_state.json"
LOG_FILE   = "/opt/ct4/logs/v15_scalper.log"
TRADES_CSV = "/opt/ct4/logs/v15_trades.csv"

# ==========================================
# LOGGING
# ==========================================
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

log = logging.getLogger("V15")
log.setLevel(logging.INFO)
log.propagate = False

fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s [V15] %(message)s', datefmt='%H:%M:%S'))
log.addHandler(fh)

if not os.getenv('NOHUP'):
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(asctime)s [V15] %(message)s', datefmt='%H:%M:%S'))
    log.addHandler(sh)

# ==========================================
# TELEGRAM
# ==========================================
async def send_tg(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={'chat_id': TG_CHAT, 'text': f"[V15-Scalper] {msg}"},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass

# ==========================================
# TRADE LOGGER
# ==========================================
def log_trade_csv(symbol, side, reason, entry_px, exit_px, amount, pnl,
                  pnl_pct, balance, entry_time,
                  adx=0, rsi=0, atr_pct=0,
                  ema50_dist=0, ema200_dist=0, btc_corr=0.5,
                  volume_ratio=1, bb_position=0.5, macd_hist_norm=0,
                  consec_candles=0, market_regime=0):
    """Write enriched trade to CSV with 20-dim Scoring AI data."""
    file_exists = os.path.exists(TRADES_CSV)
    try:
        now = datetime.now(timezone.utc)
        entry_dt = datetime.fromisoformat(entry_time) if isinstance(entry_time, str) else entry_time
        hold_hours = (now - entry_dt).total_seconds() / 3600 if entry_dt else 0

        with open(TRADES_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'close_time', 'symbol', 'side', 'reason',
                    'entry_price', 'exit_price', 'amount',
                    'pnl', 'pnl_pct', 'balance', 'entry_time',
                    'adx', 'rsi', 'atr_pct',
                    'ema50_dist_pct', 'ema200_dist_pct', 'btc_corr_4c',
                    'volume_ratio', 'hold_hours',
                    'funding_rate', 'oi_change_pct',
                    'hour_of_day', 'day_of_week',
                    'fear_greed', 'btc_dominance',
                    'market_regime', 'bb_position',
                    'macd_hist_norm', 'consec_candles',
                    'news_sentiment', 'strategy',
                ])
            writer.writerow([
                now.isoformat(), symbol, side, reason,
                entry_px, exit_px, round(amount, 4),
                round(pnl, 4), round(pnl_pct, 2), round(balance, 2),
                entry_time,
                round(adx, 1), round(rsi, 1), round(atr_pct, 5),
                round(ema50_dist, 3), round(ema200_dist, 3), round(btc_corr, 4),
                round(volume_ratio, 3), round(hold_hours, 1),
                0,          # funding_rate (Phase 3)
                0,          # oi_change_pct (Phase 3)
                now.hour,   # hour_of_day
                now.weekday(),  # day_of_week
                50,         # fear_greed (Phase 3 will fill real value)
                55,         # btc_dominance (Phase 3)
                round(market_regime, 1),
                round(bb_position, 4),
                round(macd_hist_norm, 4),
                round(consec_candles, 1),
                0,          # news_sentiment (Phase 3)
                'V15_Scalper',
            ])
    except Exception as e:
        log.error(f"CSV write error: {e}")

# ==========================================
# KILL SWITCH
# ==========================================
def check_kill(state):
    now_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get('daily_date', '') != now_date:
        state['daily_date'] = now_date
        state['daily_start'] = state['balance']
        state['killed'] = False

    if state.get('killed', False):
        return True

    bal = state['balance']
    start = state.get('daily_start', CAPITAL)
    if start > 0:
        loss_pct = (start - bal) / start * 100
        if loss_pct >= KILL_DAILY_LOSS:
            state['killed'] = True
            log.critical(f"KILL SWITCH: Daily loss {loss_pct:.1f}% >= {KILL_DAILY_LOSS}%")
            return True
    return False

# ==========================================
# STATE
# ==========================================
DEFAULT_STATE = {
    'balance': CAPITAL,
    'positions': {},
    'total_trades': 0,
    'wins': 0,
    'daily_date': '',
    'daily_start': CAPITAL,
    'killed': False,
}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding='utf-8') as f:
                s = json.load(f)
                for k, v in DEFAULT_STATE.items():
                    s.setdefault(k, v)
                return s
        except Exception:
            pass
    return dict(DEFAULT_STATE)

def save_state(state):
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)

# ==========================================
# TRAILING STOP
# ==========================================
def trail_stop(pos, cur_px):
    entry = pos['entry_price']
    risk = abs(entry - pos['initial_sl'])
    if risk <= 0:
        return pos['sl'], "Hold"

    if pos['side'] == 'LONG':
        current_r = (cur_px - entry) / risk
    else:
        current_r = (entry - cur_px) / risk

    if current_r >= TRAIL_LOCK_R and pos.get('trail_stage', 0) < 2:
        new_sl = entry + risk * 0.5 if pos['side'] == 'LONG' else entry - risk * 0.5
        pos['trail_stage'] = 2
        return new_sl, f"Lock +0.5R (R={current_r:.1f})"
    elif current_r >= TRAIL_BE_R and pos.get('trail_stage', 0) < 1:
        new_sl = entry * 1.0005 if pos['side'] == 'LONG' else entry * 0.9995
        pos['trail_stage'] = 1
        return new_sl, f"BE (R={current_r:.1f})"
    return pos['sl'], "Hold"

# ==========================================
# ANALYSIS: 15m Multi-Signal Scalper (v2 — Higher Frequency)
# ==========================================
def analyze_scalp(df, side, cur_px):
    """
    Multi-signal scalp analysis on 15m data.
    Enters on ANY of these 5 conditions:
      1. RSI7 in oversold/overbought zone + EMA9 confirmation
      2. EMA9 crosses above/below EMA21 (momentum shift)
      3. RSI7 turning: rising from <50 with close>EMA9 (LONG) or falling from >50 (SHORT)
      4. Momentum candle: green/red candle > 0.5x ATR with volume confirmation
      5. Price reclaim: price crosses back above/below EMA9 after being on the other side
    """
    if len(df) < 200:
        return False, 0, 0, 0, 0, 0, 0, 0, 0.5, 0, 0, 0, "No data"

    df['rsi7']  = ta.rsi(df['close'], length=RSI_PERIOD)
    df['rsi14'] = ta.rsi(df['close'], length=14)
    df['ema9']  = ta.ema(df['close'], length=9)
    df['ema21'] = ta.ema(df['close'], length=21)
    df['ema50'] = ta.ema(df['close'], length=50)
    df['ema200']= ta.ema(df['close'], length=200)
    df['atr']   = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx'] = adx_df['ADX_14'] if adx_df is not None else 0
    df['vol_ma'] = df['volume'].rolling(20).mean()
    
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
    streak = 0
    streaks = []
    for g in df['green']:
        if g == 1: streak = max(1, streak + 1)
        else: streak = min(-1, streak - 1) if streak <= 0 else -1
        streaks.append(streak)
    df['streak'] = streaks

    last = df.iloc[-2]  # last CLOSED candle
    prev = df.iloc[-3]  # previous candle
    rsi  = last['rsi7']
    rsi_prev = prev['rsi7'] if not pd.isna(prev['rsi7']) else 50
    ema9 = last['ema9']
    ema21 = last['ema21']
    ema9_prev = prev['ema9']
    ema21_prev = prev['ema21']
    atr  = last['atr']
    adx  = last['adx']
    rsi14= last.get('rsi14', 50)
    ema50 = last.get('ema50', cur_px)
    ema200 = last.get('ema200', cur_px)
    vol_ma = last.get('vol_ma', 0)

    if pd.isna(rsi) or pd.isna(atr) or atr == 0 or pd.isna(ema9) or pd.isna(ema21):
        return False, 0, 0, 0, 0, 0, 0, 0, 0.5, 0, 0, 0, "NaN"

    atr_pct = atr / cur_px
    ema50_dist = (cur_px - ema50) / cur_px * 100
    ema200_dist = (cur_px - ema200) / cur_px * 100
    
    bb_u = last.get('bb_upper', cur_px*1.02)
    bb_l = last.get('bb_lower', cur_px*0.98)
    bb_range = bb_u - bb_l if bb_u != bb_l else 1
    bb_pos = (cur_px - bb_l) / bb_range
    
    mh = float(last.get('macd_hist') or 0)
    macd_norm = max(-1, min(1, mh / max(cur_px * 0.001, 0.0001)))
    
    consec_candles = float(last.get('streak', 0))
    market_regime = 1.0 if (rsi14 > 55 and ema50_dist > 0 and adx > 20) else (-1.0 if (rsi14 < 45 and ema50_dist < 0 and adx > 20) else 0.0)
    
    candle_body = last['close'] - last['open']       # positive = green
    candle_size = abs(candle_body)
    vol_spike = last['volume'] > vol_ma * 1.2 if vol_ma and vol_ma > 0 else False

    if side == 'LONG':
        # Signal 1: RSI7 oversold zone
        s1 = rsi < RSI_LONG_ENTRY and last['close'] > ema9
        # Signal 2: EMA9 crosses above EMA21
        s2 = (not pd.isna(ema9_prev) and not pd.isna(ema21_prev)
              and ema9_prev <= ema21_prev and ema9 > ema21)
        # Signal 3: RSI turning up from below 50 (relaxed)
        s3 = rsi < 50 and rsi > rsi_prev and last['close'] > ema9
        # Signal 4: Strong green candle > 0.5 ATR with volume
        s4 = candle_body > atr * 0.5 and vol_spike and last['close'] > ema9
        # Signal 5: Price reclaims EMA9 (was below, now above)
        s5 = prev['close'] < ema9_prev and last['close'] > ema9 if not pd.isna(ema9_prev) else False

        signal = s1 or s2 or s3 or s4 or s5
        if not signal:
            return False, 0, 0, 0, adx, rsi14, ema50_dist, ema200_dist, bb_pos, macd_norm, consec_candles, market_regime, "No LONG signal"

        sl = cur_px - atr * ATR_SL_MULT
        tp = cur_px + atr * ATR_TP_MULT

    elif side == 'SHORT':
        # Signal 1: RSI7 overbought zone
        s1 = rsi > RSI_SHORT_ENTRY and last['close'] < ema9
        # Signal 2: EMA9 crosses below EMA21
        s2 = (not pd.isna(ema9_prev) and not pd.isna(ema21_prev)
              and ema9_prev >= ema21_prev and ema9 < ema21)
        # Signal 3: RSI turning down from above 50 (relaxed)
        s3 = rsi > 50 and rsi < rsi_prev and last['close'] < ema9
        # Signal 4: Strong red candle > 0.5 ATR with volume
        s4 = candle_body < -atr * 0.5 and vol_spike and last['close'] < ema9
        # Signal 5: Price loses EMA9 (was above, now below)
        s5 = prev['close'] > ema9_prev and last['close'] < ema9 if not pd.isna(ema9_prev) else False

        signal = s1 or s2 or s3 or s4 or s5
        if not signal:
            return False, 0, 0, 0, adx, rsi14, ema50_dist, ema200_dist, bb_pos, macd_norm, consec_candles, market_regime, "No SHORT signal"

        sl = cur_px + atr * ATR_SL_MULT
        tp = cur_px - atr * ATR_TP_MULT

    return True, sl, tp, atr_pct, adx, rsi14, ema50_dist, ema200_dist, bb_pos, macd_norm, consec_candles, market_regime, "OK"

# ==========================================
# MAIN LOOP
# ==========================================
async def main():
    state = load_state()
    exchange = ccxt.binance({'enableRateLimit': True})

    log.info(f"🚀 V15 Scalper started | Bal:${state['balance']:.2f} | {len(COINS)} coins | 15m TF")
    await send_tg(f"🚀 V15 Scalper started | Bal:${state['balance']:.2f}")

    scan_count = 0

    try:
        while True:
            scan_count += 1

            # Kill switch
            if check_kill(state):
                if scan_count % 60 == 1:
                    log.info("KILL SWITCH ACTIVE (waiting for new day)")
                save_state(state)
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            positions = state['positions']

            # ── Check open positions ──
            for sym in list(positions.keys()):
                pos = positions[sym]
                try:
                    ticker = await exchange.fetch_ticker(sym)
                    cur_px = ticker['last']
                except Exception as e:
                    log.error(f"Ticker error {sym}: {e}")
                    continue

                # Max hold check
                entry_time = datetime.fromisoformat(pos['entry_time'])
                candles_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 900
                if candles_held >= MAX_HOLD_CANDLES:
                    # Force close
                    if pos['side'] == 'LONG':
                        pnl = (cur_px - pos['entry_price']) * pos['qty']
                    else:
                        pnl = (pos['entry_price'] - cur_px) * pos['qty']
                    pnl_pct = pnl / pos['amount'] * 100

                    state['balance'] += pos['amount'] + pnl
                    state['total_trades'] += 1
                    if pnl > 0: state['wins'] += 1

                    log.info(f"⏰ TIMEOUT {sym} {pos['side']} | PnL:{pnl_pct:+.2f}% ${pnl:+.2f}")
                    await send_tg(f"⏰ TIMEOUT {sym} {pos['side']} PnL:{pnl_pct:+.2f}%")
                    log_trade_csv(sym, pos['side'], 'TIMEOUT', pos['entry_price'],
                                  cur_px, pos['amount'], pnl, pnl_pct, state['balance'],
                                  pos['entry_time'],
                                  adx=pos.get('adx', 0), rsi=pos.get('rsi', 0), atr_pct=pos.get('atr_pct', 0),
                                  ema50_dist=pos.get('ema50_dist', 0), ema200_dist=pos.get('ema200_dist', 0),
                                  bb_position=pos.get('bb_position', 0.5), macd_hist_norm=pos.get('macd_hist_norm', 0),
                                  consec_candles=pos.get('consec_candles', 0), market_regime=pos.get('market_regime', 0),
                                  btc_corr=0.5, volume_ratio=1)
                    del positions[sym]
                    save_state(state)
                    continue

                # SL/TP check
                hit_sl = hit_tp = False
                exit_px = cur_px

                if pos['side'] == 'LONG':
                    if cur_px <= pos['sl']: hit_sl, exit_px = True, pos['sl']
                    elif cur_px >= pos['tp']: hit_tp, exit_px = True, pos['tp']
                else:
                    if cur_px >= pos['sl']: hit_sl, exit_px = True, pos['sl']
                    elif cur_px <= pos['tp']: hit_tp, exit_px = True, pos['tp']

                if not hit_sl and not hit_tp:
                    new_sl, reason = trail_stop(pos, cur_px)
                    if new_sl != pos['sl']:
                        log.info(f"📐 Trail {sym}: {reason}")
                        pos['sl'] = new_sl
                    continue

                # Close position
                if pos['side'] == 'LONG':
                    pnl = (exit_px - pos['entry_price']) * pos['qty']
                else:
                    pnl = (pos['entry_price'] - exit_px) * pos['qty']
                pnl_pct = pnl / pos['amount'] * 100

                state['balance'] += pos['amount'] + pnl
                state['total_trades'] += 1
                if pnl > 0: state['wins'] += 1

                reason_str = "TP ✅" if hit_tp else "SL ❌"
                emoji = "💰" if hit_tp else "🛑"
                log.info(f"{emoji} {reason_str} {sym} {pos['side']} | "
                         f"PnL:{pnl_pct:+.2f}% ${pnl:+.2f} | Bal:${state['balance']:.2f}")
                await send_tg(f"{emoji} {reason_str} {sym} {pos['side']} "
                              f"PnL:{pnl_pct:+.2f}% Bal:${state['balance']:.2f}")
                log_trade_csv(sym, pos['side'], 'TP' if hit_tp else 'SL',
                              pos['entry_price'], exit_px, pos['amount'],
                              pnl, pnl_pct, state['balance'], pos['entry_time'],
                              adx=pos.get('adx', 0), rsi=pos.get('rsi', 0), atr_pct=pos.get('atr_pct', 0),
                              ema50_dist=pos.get('ema50_dist', 0), ema200_dist=pos.get('ema200_dist', 0),
                              bb_position=pos.get('bb_position', 0.5), macd_hist_norm=pos.get('macd_hist_norm', 0),
                              consec_candles=pos.get('consec_candles', 0), market_regime=pos.get('market_regime', 0),
                              btc_corr=0.5, volume_ratio=1)
                del positions[sym]
                save_state(state)

            # ── Look for new entries ──
            if len(positions) < MAX_POSITIONS:
                for sym in COINS:
                    if sym in positions or len(positions) >= MAX_POSITIONS:
                        continue

                    try:
                        ohlcv = await exchange.fetch_ohlcv(sym, '15m', limit=200)
                        df = pd.DataFrame(ohlcv, columns=[
                            'timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        cur_px = df['close'].iloc[-1]

                        for side in ['LONG', 'SHORT']:
                            if sym in positions:
                                break

                            ok, sl, tp, atr_pct, adx, rsi, ema50_dist, ema200_dist, bb_pos, macd_norm, consec_candles, market_regime, reason = analyze_scalp(
                                df.copy(), side, cur_px)

                            if not ok:
                                continue

                            # Position sizing
                            sl_dist = abs(cur_px - sl) / cur_px
                            if sl_dist <= 0:
                                continue
                            amt = state['balance'] * RISK_PER_TRADE / sl_dist
                            amt = min(amt, state['balance'] * MAX_POS_PCT)
                            if amt < 5 or amt > state['balance']:
                                continue

                            # Open position
                            positions[sym] = {
                                'side': side,
                                'entry_price': cur_px,
                                'qty': amt / cur_px,
                                'amount': amt,
                                'sl': sl,
                                'initial_sl': sl,
                                'tp': tp,
                                'entry_time': datetime.now(timezone.utc).isoformat(),
                                'trail_stage': 0,
                                'adx': adx,
                                'rsi': rsi,
                                'atr_pct': atr_pct,
                                'ema50_dist': ema50_dist,
                                'ema200_dist': ema200_dist,
                                'bb_position': bb_pos,
                                'macd_hist_norm': macd_norm,
                                'consec_candles': consec_candles,
                                'market_regime': market_regime,
                            }
                            state['balance'] -= amt

                            log.info(f"🎯 ENTRY {side} {sym} @ {cur_px:.6f} | "
                                     f"SL:{sl:.6f} TP:{tp:.6f} | ${amt:.2f} | "
                                     f"RSI7:{rsi:.0f} ADX:{adx:.0f}")
                            await send_tg(f"🎯 ENTRY {side} {sym} @ {cur_px:.6f} "
                                          f"RSI7:{rsi:.0f} ${amt:.2f}")
                            save_state(state)

                    except Exception as e:
                        log.error(f"Scan error {sym}: {e}")

            # ── Status log ──
            if scan_count % 20 == 1:
                wr = (state['wins'] / state['total_trades'] * 100
                      if state['total_trades'] > 0 else 0)
                log.info(f"  Bal:${state['balance']:.2f} Pos:{len(positions)}/{MAX_POSITIONS} "
                         f"T:{state['total_trades']} WR:{wr:.0f}%")

            save_state(state)
            await asyncio.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        await exchange.close()

if __name__ == '__main__':
    asyncio.run(main())
