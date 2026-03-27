"""
🧪 LAB V10 — Regime Detection + Multi-Timeframe Backtest
=========================================================
Tests regime-aware trading vs V9.1 baseline on real historical data.
Downloads 1h + 4h OHLCV, identifies market regimes (trending/ranging),
adapts entry thresholds and TP/SL per regime.
"""
import ccxt, pandas as pd, pandas_ta as ta, numpy as np
from datetime import datetime, timedelta
import json

# ═══════════════════════════════════════════════════════
# CONFIG (mirrors V9.1 config.json defaults)
# ═══════════════════════════════════════════════════════

CAPITAL = 30.0
MAX_POSITIONS = 3
FEE_PCT = 0.1
TRAILING_TRIGGER = 1.5

# ATR dynamic SL/TP
ATR_SL_MULT = 1.5
ATR_TP_MULT = 2.5
ATR_SL_MIN, ATR_SL_MAX = 1.0, 5.0
ATR_TP_MIN, ATR_TP_MAX = 1.5, 8.0
ATR_TRAIL_MULT = 0.8
ATR_TRAIL_MIN = 0.8

TIMEOUT_HOURS = 4
TIMEOUT_MIN_GAIN = 0.5
MIN_DIMS = 3

COINS = [
    'DOGE/USDT', 'XRP/USDT', 'ADA/USDT', 'SOL/USDT', 'AVAX/USDT',
    'PEPE/USDT', 'FLOKI/USDT', 'BONK/USDT', 'WIF/USDT', 'SHIB/USDT',
    'GALA/USDT', 'FET/USDT', 'LINK/USDT', 'NEAR/USDT', 'SUI/USDT',
    'BTC/USDT',
]

DAYS = 14  # 2 weeks of data

# ═══════════════════════════════════════════════════════
# DATA DOWNLOAD
# ═══════════════════════════════════════════════════════

def download_data(coins, days):
    ex = ccxt.binance({'enableRateLimit': True})
    since = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    data = {}
    for sym in coins:
        try:
            print(f"  Downloading {sym}...", end=" ")
            ohlcv_1h = ex.fetch_ohlcv(sym, '1h', since=since, limit=days*24)
            ohlcv_4h = ex.fetch_ohlcv(sym, '4h', since=since, limit=days*6)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['ts','open','high','low','close','volume'])
            df_1h['ts'] = pd.to_datetime(df_1h['ts'], unit='ms')
            df_1h.set_index('ts', inplace=True)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['ts','open','high','low','close','volume'])
            df_4h['ts'] = pd.to_datetime(df_4h['ts'], unit='ms')
            df_4h.set_index('ts', inplace=True)
            data[sym] = {'1h': df_1h, '4h': df_4h}
            print(f"{len(df_1h)} 1h + {len(df_4h)} 4h candles")
        except Exception as e:
            print(f"SKIP ({e})")
    return data

# ═══════════════════════════════════════════════════════
# REGIME DETECTION (on 4h data)
# ═══════════════════════════════════════════════════════

def detect_regime(df_4h, idx_1h):
    """Given 4h DataFrame and a 1h timestamp, detect market regime."""
    # Find latest 4h candle at or before this 1h timestamp
    mask = df_4h.index <= idx_1h
    if mask.sum() < 20:
        return 'unknown', 0
    
    recent_4h = df_4h.loc[mask]
    close = recent_4h['close']
    
    # ADX on 4h (last 14 candles = 56 hours)
    adx = ta.adx(recent_4h['high'], recent_4h['low'], close, 14)
    if adx is None:
        return 'unknown', 0
    adx_col = [c for c in adx.columns if 'ADX' in c]
    if not adx_col:
        return 'unknown', 0
    adx_val = float(adx[adx_col[0]].iloc[-1])
    
    # EMA trend on 4h
    ema20 = ta.ema(close, 20)
    ema50 = ta.ema(close, 50)
    if ema20 is None or ema50 is None:
        trend = 'neutral'
    else:
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        trend = 'up' if e20 > e50 else 'down'
    
    if adx_val < 20:
        regime = 'ranging'
    elif adx_val >= 25:
        regime = f'trending_{trend}'
    else:
        regime = f'weak_trend_{trend}'    
    
    return regime, adx_val

# ═══════════════════════════════════════════════════════
# ANALYZE (simplified V9.1 scoring + dims)
# ═══════════════════════════════════════════════════════

def analyze(df_1h, symbol):
    if len(df_1h) < 50: return None
    df = df_1h.iloc[:-1]  # Closed candles only
    close = df['close']
    price = float(df['close'].iloc[-1])
    
    result = {'symbol': symbol, 'price': price, 'long_score': 0, 'short_score': 0,
              'long_signals': [], 'short_signals': [], 'long_dims': 0, 'short_dims': 0}
    
    # --- Price Zone (unified Range + BB, max 20) ---
    h24 = df['high'].tail(24).max(); l24 = df['low'].tail(24).min()
    rng = h24 - l24
    rpos = (price - l24) / rng if rng > 0 else 0.5
    pz_long = 0; pz_short = 0
    if rpos < 0.15: pz_long = 20
    elif rpos < 0.30: pz_long = 15
    elif rpos < 0.45: pz_long = 8
    if rpos > 0.85: pz_short = 20
    elif rpos > 0.70: pz_short = 15
    elif rpos > 0.55: pz_short = 8
    
    bb = ta.bbands(close, 20, 2)
    if bb is not None:
        bbl = [c for c in bb.columns if c.startswith('BBL_')]
        bbu = [c for c in bb.columns if c.startswith('BBU_')]
        if bbl and bbu:
            bl = float(bb[bbl[0]].iloc[-1]); bh = float(bb[bbu[0]].iloc[-1]); br = bh - bl
            if br > 0:
                bp = (price - bl) / br
                result['bb_pos'] = bp
                if bp < 0.10: pz_long = max(pz_long, 20)
                elif bp < 0.25: pz_long = max(pz_long, 12)
                if bp > 0.90: pz_short = max(pz_short, 20)
                elif bp > 0.75: pz_short = max(pz_short, 12)
    result['long_score'] += min(pz_long, 20)
    result['short_score'] += min(pz_short, 20)
    
    # --- RSI ---
    rsi = ta.rsi(close, 14)
    r14 = float(rsi.iloc[-1]) if rsi is not None and not pd.isna(rsi.iloc[-1]) else 50
    result['rsi_14'] = r14
    if r14 < 25: result['long_score'] += 20
    elif r14 < 35: result['long_score'] += 15
    elif r14 < 45: result['long_score'] += 8
    if r14 > 75: result['short_score'] += 20
    elif r14 > 65: result['short_score'] += 15
    elif r14 > 55: result['short_score'] += 8
    
    # --- Volume ---
    vs = df['volume'].rolling(20).mean()
    vr = float(df['volume'].iloc[-1] / vs.iloc[-1]) if vs.iloc[-1] > 0 else 1
    result['vol_ratio'] = vr
    if vr > 3: result['long_score'] += 15; result['short_score'] += 15
    elif vr > 2: result['long_score'] += 10; result['short_score'] += 10
    elif vr > 1.5: result['long_score'] += 5; result['short_score'] += 5
    
    # --- EMA ---
    ema9 = ta.ema(close, 9); ema21 = ta.ema(close, 21)
    if ema9 is not None and ema21 is not None:
        e9 = float(ema9.iloc[-1]); e21 = float(ema21.iloc[-1])
        result['ema_trend'] = 'bullish' if e9 > e21 else 'bearish'
        if e9 > e21: result['long_score'] += 10
        else: result['short_score'] += 10
    else:
        result['ema_trend'] = 'neutral'
    
    # --- MACD ---
    mc = ta.macd(close, 12, 26, 9)
    macd_h = 0
    if mc is not None:
        cols = mc.columns.tolist()
        if len(cols) >= 3: macd_h = float(mc[cols[2]].iloc[-1])
    result['macd_hist'] = macd_h
    
    # --- ROC ---
    roc1 = float((close.iloc[-1]/close.iloc[-2]-1)*100) if len(close)>1 else 0
    roc3 = float((close.iloc[-1]/close.iloc[-4]-1)*100) if len(close)>3 else 0
    if roc1 > 0 and roc3 < -2: result['long_score'] += 15
    if roc1 < 0 and roc3 > 2: result['short_score'] += 15
    
    # --- Momentum/Trend following ---
    chg1h = roc1
    chg24 = float((close.iloc[-1]/close.iloc[-24]-1)*100) if len(close) > 24 else 0
    ema_bull = result.get('ema_trend') == 'bullish'
    if ema_bull and chg24 > 10 and chg1h < 0: result['long_score'] += 15
    if chg1h > 2 and chg24 > 5 and vr > 1.5: result['long_score'] += 18
    if chg1h < -2 and chg24 < -5 and vr > 1.5: result['short_score'] += 18
    if not ema_bull and chg24 < -10 and chg1h > 0.5: result['short_score'] += 20
    
    result['change_24h'] = chg24
    
    # --- ATR ---
    atr_raw = ta.atr(df['high'], df['low'], close, 14)
    if atr_raw is not None and not pd.isna(atr_raw.iloc[-1]):
        result['atr_pct'] = float(float(atr_raw.iloc[-1]) / price * 100)
    else:
        result['atr_pct'] = 2.0
    
    # --- DIMENSIONS ---
    ld = 0; sd = 0
    if result.get('ema_trend') == 'bullish': ld += 1
    if result.get('ema_trend') == 'bearish': sd += 1
    if r14 < 40 or macd_h > 0: ld += 1
    if r14 > 60 or macd_h < 0: sd += 1
    if pz_long >= 12 or result.get('bb_pos', 0.5) < 0.3 or rpos < 0.3: ld += 1
    if pz_short >= 12 or result.get('bb_pos', 0.5) > 0.7 or rpos > 0.7: sd += 1
    if vr > 1.3: ld += 1; sd += 1
    result['long_dims'] = ld
    result['short_dims'] = sd
    result['score'] = max(result['long_score'], result['short_score'])
    
    return result

# ═══════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════

def backtest(data, use_regime=False, label=""):
    balance = CAPITAL
    positions = {}
    trades = []
    regime_stats = {'trending_up': 0, 'trending_down': 0, 'ranging': 0, 'weak_trend_up': 0, 'weak_trend_down': 0, 'unknown': 0}
    
    # Get all 1h timestamps across all coins
    all_ts = set()
    for sym, d in data.items():
        all_ts.update(d['1h'].index.tolist())
    all_ts = sorted(all_ts)
    
    # Skip first 50 candles for indicator warmup
    all_ts = all_ts[50:]
    
    for ts in all_ts:
        # Check exits
        for sym in list(positions.keys()):
            if sym not in data: continue
            df = data[sym]['1h']
            if ts not in df.index: continue
            pos = positions[sym]
            price = float(df.loc[ts, 'close'])
            side = pos['side']
            
            if side == 'long':
                pnl_pct = (price / pos['entry'] - 1) * 100
                if price > pos['peak']: pos['peak'] = price
            else:
                pnl_pct = (pos['entry'] / price - 1) * 100
                if price < pos['peak']: pos['peak'] = price
            
            # Trailing
            trail_dist = max(ATR_TRAIL_MIN / 100, pos['atr_pct'] / 100 * ATR_TRAIL_MULT)
            if not pos['trailing'] and pnl_pct >= TRAILING_TRIGGER:
                pos['trailing'] = True
                pos['sl'] = pos['entry'] * (1.001 if side == 'long' else 0.999)
            if pos['trailing']:
                if side == 'long':
                    ns = pos['peak'] * (1 - trail_dist)
                    if ns > pos['sl']: pos['sl'] = ns
                else:
                    ns = pos['peak'] * (1 + trail_dist)
                    if ns < pos['sl']: pos['sl'] = ns
            
            reason = None
            if side == 'long':
                if price >= pos['tp']: reason = 'TP'
                elif price <= pos['sl']: reason = 'TRAIL' if pos['trailing'] else 'SL'
            else:
                if price <= pos['tp']: reason = 'TP'
                elif price >= pos['sl']: reason = 'TRAIL' if pos['trailing'] else 'SL'
            
            hours = (ts - pos['entry_ts']).total_seconds() / 3600
            if hours >= TIMEOUT_HOURS and pnl_pct < TIMEOUT_MIN_GAIN:
                reason = 'TIMEOUT'
            
            if reason:
                pnl_usd = pos['amount'] * pnl_pct / 100
                balance += pos['amount'] + pnl_usd
                trades.append({
                    'symbol': sym, 'side': side, 'reason': reason,
                    'pnl': pnl_usd, 'pnl_pct': pnl_pct, 'hours': hours,
                    'regime': pos.get('regime', 'unknown'),
                    'entry_ts': pos['entry_ts'], 'exit_ts': ts,
                })
                del positions[sym]
        
        # Try entries
        if len(positions) >= MAX_POSITIONS: continue
        if balance < 5: continue
        
        results_at_ts = []
        for sym, d in data.items():
            if sym == 'BTC/USDT': continue  # Don't trade BTC directly
            if sym in positions: continue
            df = d['1h']
            if ts not in df.index: continue
            idx = df.index.get_loc(ts)
            if idx < 50: continue
            
            window = df.iloc[:idx+1]
            a = analyze(window, sym)
            if a is None: continue
            
            # Regime detection (V10)
            if use_regime and sym in data and '4h' in data[sym]:
                regime, adx_val = detect_regime(data[sym]['4h'], ts)
                a['regime'] = regime
                a['adx_4h'] = adx_val
                
                # === REGIME ADAPTATION ===
                if 'ranging' in regime:
                    min_score = 65  # Much more selective in ranging
                    min_dims = 4   # Need ALL dimensions
                elif 'trending_up' in regime:
                    min_score = 50   # More aggressive for longs in uptrend
                    min_dims = 3
                    a['long_score'] += 10  # Bias toward longs
                elif 'trending_down' in regime:
                    min_score = 50
                    min_dims = 3
                    a['short_score'] += 10  # Bias toward shorts
                else:
                    min_score = 55
                    min_dims = 3
            else:
                regime = 'unknown'
                min_score = 55
                min_dims = MIN_DIMS
                a['regime'] = regime
            
            regime_stats[regime.split('_')[0] if '_' in regime else regime] = regime_stats.get(regime.split('_')[0] if '_' in regime else regime, 0) + 1
            
            # BTC crash filter
            if 'BTC/USDT' in data:
                btc_df = data['BTC/USDT']['1h']
                if ts in btc_df.index:
                    btc_idx = btc_df.index.get_loc(ts)
                    if btc_idx > 24:
                        btc_chg = (float(btc_df['close'].iloc[btc_idx]) / float(btc_df['close'].iloc[btc_idx-24]) - 1) * 100
                        if btc_chg < -3:
                            a['btc_blocked'] = True
            
            results_at_ts.append(a)
        
        results_at_ts.sort(key=lambda x: -x['score'])
        
        for coin in results_at_ts:
            if len(positions) >= MAX_POSITIONS: break
            if balance < 5: break
            
            ls = coin['long_score']; ss = coin['short_score']
            ld = coin['long_dims']; sd = coin['short_dims']
            ema = coin.get('ema_trend', 'neutral')
            atr_pct = coin.get('atr_pct', 2.0)
            
            entered = False
            
            # LONG
            ema_ok = ema == 'bullish' or ls >= 70
            if ls >= min_score and ema_ok and ld >= min_dims and not coin.get('btc_blocked'):
                sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct * ATR_SL_MULT))
                tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct * ATR_TP_MULT))
                # Regime adaptation for exits
                if use_regime and 'trending_up' in coin.get('regime', ''):
                    tp_pct *= 1.3  # Wider TP in uptrend
                amt = min(CAPITAL / MAX_POSITIONS, balance * 0.33)
                if amt >= 3:
                    fee = amt * FEE_PCT / 100
                    balance -= amt
                    p = coin['price']
                    positions[coin['symbol']] = {
                        'side': 'long', 'entry': p, 'amount': amt - fee,
                        'tp': p * (1 + tp_pct/100), 'sl': p * (1 - sl_pct/100),
                        'peak': p, 'trailing': False, 'atr_pct': atr_pct,
                        'entry_ts': ts, 'regime': coin.get('regime', 'unknown'),
                    }
                    entered = True
            
            # SHORT
            if not entered:
                ema_ok = ema == 'bearish' or ss >= 70
                if ss >= min_score and ema_ok and sd >= min_dims:
                    sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct * ATR_SL_MULT))
                    tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct * ATR_TP_MULT))
                    if use_regime and 'trending_down' in coin.get('regime', ''):
                        tp_pct *= 1.3
                    amt = min(CAPITAL / MAX_POSITIONS, balance * 0.33)
                    if amt >= 3:
                        fee = amt * FEE_PCT / 100
                        balance -= amt
                        p = coin['price']
                        positions[coin['symbol']] = {
                            'side': 'short', 'entry': p, 'amount': amt - fee,
                            'tp': p * (1 - tp_pct/100), 'sl': p * (1 + sl_pct/100),
                            'peak': p, 'trailing': False, 'atr_pct': atr_pct,
                            'entry_ts': ts, 'regime': coin.get('regime', 'unknown'),
                        }
    
    # Close remaining positions at last price
    for sym in list(positions.keys()):
        pos = positions[sym]
        df = data[sym]['1h']
        price = float(df['close'].iloc[-1])
        side = pos['side']
        if side == 'long':
            pnl_pct = (price / pos['entry'] - 1) * 100
        else:
            pnl_pct = (pos['entry'] / price - 1) * 100
        pnl_usd = pos['amount'] * pnl_pct / 100
        balance += pos['amount'] + pnl_usd
        trades.append({
            'symbol': sym, 'side': side, 'reason': 'END',
            'pnl': pnl_usd, 'pnl_pct': pnl_pct,
            'regime': pos.get('regime', 'unknown'),
        })
    
    # Results
    wins = sum(1 for t in trades if t['pnl'] > 0)
    losses = sum(1 for t in trades if t['pnl'] <= 0)
    total_pnl = sum(t['pnl'] for t in trades)
    wr = wins / len(trades) * 100 if trades else 0
    avg_win = np.mean([t['pnl_pct'] for t in trades if t['pnl'] > 0]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in trades if t['pnl'] <= 0]) if losses else 0
    
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Trades: {len(trades)} | W:{wins} L:{losses} | WR: {wr:.1f}%")
    print(f"  PnL: ${total_pnl:+.4f} | Balance: ${balance:.2f}")
    print(f"  Avg Win: {avg_win:+.1f}% | Avg Loss: {avg_loss:+.1f}%")
    print(f"  Profit Factor: {abs(sum(t['pnl'] for t in trades if t['pnl'] > 0) / sum(t['pnl'] for t in trades if t['pnl'] < 0)):.2f}" if losses > 0 and any(t['pnl'] < 0 for t in trades) else "  Profit Factor: ∞")
    
    # By side
    longs = [t for t in trades if t['side'] == 'long']
    shorts = [t for t in trades if t['side'] == 'short']
    lw = sum(1 for t in longs if t['pnl'] > 0)
    sw = sum(1 for t in shorts if t['pnl'] > 0)
    print(f"  LONGs: {len(longs)} (WR:{lw/len(longs)*100:.0f}%)" if longs else "  LONGs: 0")
    print(f"  SHORTs: {len(shorts)} (WR:{sw/len(shorts)*100:.0f}%)" if shorts else "  SHORTs: 0")
    
    # By close reason
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = {'count': 0, 'pnl': 0, 'wins': 0}
        reasons[r]['count'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0: reasons[r]['wins'] += 1
    print(f"  {'Reason':<10} {'Trades':>6} {'WR':>6} {'PnL':>10}")
    for r, d in sorted(reasons.items(), key=lambda x: -x[1]['count']):
        rwr = d['wins']/d['count']*100 if d['count'] else 0
        print(f"  {r:<10} {d['count']:>6} {rwr:>5.0f}% ${d['pnl']:>+8.4f}")
    
    # By regime (if available)
    if use_regime:
        print(f"\n  === REGIME BREAKDOWN ===")
        for reg in ['trending_up', 'trending_down', 'ranging', 'weak_trend_up', 'weak_trend_down', 'unknown']:
            rt = [t for t in trades if t.get('regime', '').startswith(reg.split('_')[0]) if reg.split('_')[-1] in t.get('regime', '') or '_' not in reg]
            if not rt: continue
            rw = sum(1 for t in rt if t['pnl'] > 0)
            rpnl = sum(t['pnl'] for t in rt)
            print(f"  {reg:<20} {len(rt):>3} trades WR:{rw/len(rt)*100:>5.1f}% PnL:${rpnl:>+.4f}")
    
    return {'trades': len(trades), 'wr': wr, 'pnl': total_pnl, 'balance': balance, 'details': trades}

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    print("🧪 LAB V10 — Regime Detection + Multi-Timeframe")
    print(f"   {len(COINS)} coins × {DAYS} days\n")
    
    print("📥 Downloading data...")
    data = download_data(COINS, DAYS)
    
    print(f"\n✅ Downloaded {len(data)} coins")
    
    # Test 1: V9.1 baseline (no regime detection)
    r1 = backtest(data, use_regime=False, label="🔵 V9.1 BASELINE (no regime)")
    
    # Test 2: V10 with regime detection
    r2 = backtest(data, use_regime=True, label="🟢 V10 REGIME DETECTION")
    
    # Comparison
    print(f"\n{'='*60}")
    print(f"  📊 COMPARISON")
    print(f"{'='*60}")
    print(f"  {'Metric':<20} {'V9.1':>12} {'V10 Regime':>12} {'Diff':>10}")
    print(f"  {'Trades':<20} {r1['trades']:>12} {r2['trades']:>12} {r2['trades']-r1['trades']:>+10}")
    print(f"  {'Win Rate':<20} {r1['wr']:>11.1f}% {r2['wr']:>11.1f}% {r2['wr']-r1['wr']:>+9.1f}%")
    print(f"  {'PnL':<20} ${r1['pnl']:>+10.4f} ${r2['pnl']:>+10.4f} ${r2['pnl']-r1['pnl']:>+8.4f}")
    print(f"  {'Balance':<20} ${r1['balance']:>10.2f} ${r2['balance']:>10.2f} ${r2['balance']-r1['balance']:>+8.2f}")
    
    winner = "V10 REGIME" if r2['pnl'] > r1['pnl'] else "V9.1 BASELINE"
    print(f"\n  🏆 Winner: {winner}")
