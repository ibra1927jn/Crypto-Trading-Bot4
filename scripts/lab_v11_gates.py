"""
🧪 LAB V11 — 5 Hard Gates: WR Improvement Test
================================================
Tests 3 configurations on 14 days of real market data:
  - V10 Baseline (regime detection)
  - V11 Phase 1 (5 hard gates added)

Hard Gates:
1. REGIME DIRECTION LOCK: no SHORTs in trending_up (need score≥75 to override)
2. RSI GATE: LONG needs RSI<50, SHORT needs RSI>50 (override at score≥70)
3. SL BAN: rigorous double-check before entry (prevent WAXP-style revenge)
4. NEWS QUALITY: base technical score must pass threshold before news can help
5. ATR TOXICITY: skip coins with ATR%>10 (too volatile, stops too wide)
"""
import ccxt, pandas as pd, pandas_ta as ta, numpy as np
from datetime import datetime, timedelta

# ════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════
CAPITAL       = 30.0
MAX_POSITIONS = 3
FEE_PCT       = 0.1
TRAILING_TRIGGER = 1.5
ATR_SL_MULT, ATR_TP_MULT = 1.5, 2.5
ATR_SL_MIN, ATR_SL_MAX   = 1.0, 5.0
ATR_TP_MIN, ATR_TP_MAX   = 1.5, 8.0
ATR_TRAIL_MULT, ATR_TRAIL_MIN = 0.8, 0.8
TIMEOUT_HOURS    = 4
TIMEOUT_MIN_GAIN = 0.5
MIN_DIMS         = 3
DAYS = 14

# V11 GATE PARAMETERS
V11_RSI_LONG_MAX   = 50   # LONG: RSI must be below this
V11_RSI_SHORT_MIN  = 50   # SHORT: RSI must be above this
V11_RSI_OVERRIDE   = 70   # Score above this overrides RSI gate
V11_REGIME_OVERRIDE= 75   # Score above this overrides regime direction lock
V11_ATR_MAX        = 10.0 # Skip coins with ATR% above this
V11_NEWS_BASE_MIN  = 40   # Base score (ex-news) needed before news bonus applies

COINS = [
    'DOGE/USDT','XRP/USDT','ADA/USDT','SOL/USDT','AVAX/USDT',
    'PEPE/USDT','FLOKI/USDT','BONK/USDT','WIF/USDT','SHIB/USDT',
    'GALA/USDT','FET/USDT','LINK/USDT','NEAR/USDT','SUI/USDT',
    'COS/USDT','NTRN/USDT','WAXP/USDT','PHA/USDT','ATOM/USDT',
    'STO/USDT','FORTH/USDT','SXT/USDT','BTC/USDT',
]

# ════════════════════════════════════════════════
# DATA DOWNLOAD
# ════════════════════════════════════════════════
def download_data(coins, days):
    ex = ccxt.binance({'enableRateLimit': True})
    since = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    data = {}
    for sym in coins:
        try:
            print(f"  {sym}...", end=" ", flush=True)
            o1 = ex.fetch_ohlcv(sym, '1h', since=since, limit=days*24)
            o4 = ex.fetch_ohlcv(sym, '4h', since=since, limit=days*6)
            def mk(rows):
                df = pd.DataFrame(rows, columns=['ts','open','high','low','close','volume'])
                df['ts'] = pd.to_datetime(df['ts'], unit='ms')
                df.set_index('ts', inplace=True)
                return df
            data[sym] = {'1h': mk(o1), '4h': mk(o4)}
            print(f"OK ({len(o1)})")
        except Exception as e:
            print(f"SKIP ({e})")
    return data

# ════════════════════════════════════════════════
# REGIME DETECTION
# ════════════════════════════════════════════════
def detect_regime(df_4h):
    if df_4h is None or len(df_4h) < 50:
        return 'unknown', 0
    close = df_4h['close']
    adx = ta.adx(df_4h['high'], df_4h['low'], close, 14)
    if adx is None: return 'unknown', 0
    adx_col = [c for c in adx.columns if 'ADX' in c]
    if not adx_col: return 'unknown', 0
    adx_val = float(adx[adx_col[0]].iloc[-1])
    ema20 = ta.ema(close, 20); ema50 = ta.ema(close, 50)
    direction = 'up' if (ema20 is not None and ema50 is not None and
                         float(ema20.iloc[-1]) > float(ema50.iloc[-1])) else 'down'
    if adx_val < 20:   return 'ranging', adx_val
    elif adx_val >= 25: return f'trending_{direction}', adx_val
    else:               return f'weak_trend_{direction}', adx_val

# ════════════════════════════════════════════════
# ANALYZE (V9.1 base — closed candles, unified PZ)
# ════════════════════════════════════════════════
def analyze(df_1h, symbol):
    if len(df_1h) < 50: return None
    df = df_1h.iloc[:-1]         # Closed candles only
    close = df['close']
    price = float(df_1h['close'].iloc[-1])

    result = {
        'symbol': symbol, 'price': price,
        'long_score': 0, 'short_score': 0,
        'long_score_base': 0, 'short_score_base': 0,  # pre-news scores
        'long_dims': 0, 'short_dims': 0, 'signals': [],
    }

    # Price Zone (unified Range+BB, max 20)
    h24 = df['high'].tail(24).max(); l24 = df['low'].tail(24).min(); rng = h24 - l24
    rpos = (price - l24) / rng if rng > 0 else 0.5
    pz_l, pz_s = 0, 0
    if rpos < 0.15: pz_l = 20
    elif rpos < 0.30: pz_l = 15
    elif rpos < 0.45: pz_l = 8
    if rpos > 0.85: pz_s = 20
    elif rpos > 0.70: pz_s = 15
    elif rpos > 0.55: pz_s = 8
    bb = ta.bbands(close, 20, 2)
    if bb is not None:
        bbl=[c for c in bb.columns if c.startswith('BBL_')]
        bbu=[c for c in bb.columns if c.startswith('BBU_')]
        if bbl and bbu:
            bl=float(bb[bbl[0]].iloc[-1]); bh=float(bb[bbu[0]].iloc[-1]); br=bh-bl
            if br > 0:
                bp = (price - bl) / br; result['bb_pos'] = bp
                if bp < 0.10: pz_l = max(pz_l, 20)
                elif bp < 0.25: pz_l = max(pz_l, 12)
                if bp > 0.90: pz_s = max(pz_s, 20)
                elif bp > 0.75: pz_s = max(pz_s, 12)
    result['long_score'] += min(pz_l, 20); result['short_score'] += min(pz_s, 20)

    # RSI
    rsi = ta.rsi(close, 14)
    r14 = float(rsi.iloc[-1]) if rsi is not None and not pd.isna(rsi.iloc[-1]) else 50
    result['rsi_14'] = r14
    if r14 < 25: result['long_score'] += 20
    elif r14 < 35: result['long_score'] += 15
    elif r14 < 45: result['long_score'] += 8
    if r14 > 75: result['short_score'] += 20
    elif r14 > 65: result['short_score'] += 15
    elif r14 > 55: result['short_score'] += 8

    # Volume
    vs = df['volume'].rolling(20).mean()
    vr = float(df['volume'].iloc[-1] / vs.iloc[-1]) if vs.iloc[-1] > 0 else 1
    result['vol_ratio'] = vr
    if vr > 3: result['long_score'] += 15; result['short_score'] += 15
    elif vr > 2: result['long_score'] += 10; result['short_score'] += 10
    elif vr > 1.5: result['long_score'] += 5; result['short_score'] += 5

    # EMA trend
    ema9 = ta.ema(close, 9); ema21 = ta.ema(close, 21)
    if ema9 is not None and ema21 is not None:
        e9 = float(ema9.iloc[-1]); e21 = float(ema21.iloc[-1])
        result['ema_trend'] = 'bullish' if e9 > e21 else 'bearish'
        if e9 > e21: result['long_score'] += 10
        else: result['short_score'] += 10
    else:
        result['ema_trend'] = 'neutral'

    # MACD
    mc = ta.macd(close, 12, 26, 9)
    macd_h = 0
    if mc is not None and len(mc.columns) >= 3:
        macd_h = float(mc[mc.columns[2]].iloc[-1])
    result['macd_hist'] = macd_h

    # ROC
    roc1 = float((close.iloc[-1]/close.iloc[-2]-1)*100) if len(close)>1 else 0
    roc3 = float((close.iloc[-1]/close.iloc[-4]-1)*100) if len(close)>3 else 0
    if roc1 > 0 and roc3 < -2: result['long_score'] += 15
    if roc1 < 0 and roc3 > 2: result['short_score'] += 15

    # Trend following
    chg24 = float((close.iloc[-1]/close.iloc[-24]-1)*100) if len(close) > 24 else 0
    ema_bull = result.get('ema_trend') == 'bullish'
    if ema_bull and chg24 > 10 and roc1 < 0: result['long_score'] += 15
    if roc1 > 2 and chg24 > 5 and vr > 1.5: result['long_score'] += 18
    if roc1 < -2 and chg24 < -5 and vr > 1.5: result['short_score'] += 18
    if not ema_bull and chg24 < -10 and roc1 > 0.5: result['short_score'] += 20
    result['change_24h'] = chg24

    # ATR
    atr_raw = ta.atr(df['high'], df['low'], close, 14)
    if atr_raw is not None and not pd.isna(atr_raw.iloc[-1]):
        result['atr_pct'] = float(float(atr_raw.iloc[-1]) / price * 100)
    else:
        result['atr_pct'] = 2.0

    # DIMENSIONS
    ld = sd = 0
    if result.get('ema_trend') == 'bullish': ld += 1
    if result.get('ema_trend') == 'bearish': sd += 1
    if r14 < 40 or macd_h > 0: ld += 1
    if r14 > 60 or macd_h < 0: sd += 1
    if pz_l >= 12 or result.get('bb_pos', 0.5) < 0.3 or rpos < 0.3: ld += 1
    if pz_s >= 12 or result.get('bb_pos', 0.5) > 0.7 or rpos > 0.7: sd += 1
    if vr > 1.3: ld += 1; sd += 1
    result['long_dims'] = ld; result['short_dims'] = sd
    result['score'] = max(result['long_score'], result['short_score'])

    # Save pre-news base scores (for gate 4)
    result['long_score_base'] = result['long_score']
    result['short_score_base'] = result['short_score']

    return result

# ════════════════════════════════════════════════
# V11 HARD GATES
# ════════════════════════════════════════════════
def apply_v11_gates(coin, side, regime, sl_bans, symbol, cfg):
    """Returns (allowed, rejection_reason) with all 5 V11 gates."""
    ls = coin['long_score']; ss = coin['short_score']
    score = ls if side == 'long' else ss
    r14 = coin.get('rsi_14', 50)
    atr_pct = coin.get('atr_pct', 2.0)

    # GATE 5: ATR toxicity
    if atr_pct > cfg['atr_max']:
        return False, f'ATR {atr_pct:.1f}%>{cfg["atr_max"]}% (toxic)'

    # GATE 3: SL ban
    if symbol in sl_bans:
        ban_ts, strike_count = sl_bans[symbol]
        if datetime.utcnow().timestamp() < ban_ts:
            return False, f'SL ban ({strike_count} strikes)'

    # GATE 1: Regime direction lock (hard)
    if cfg.get('regime_lock'):
        if 'trending_up' in regime and side == 'short':
            if score < cfg['regime_override']:
                return False, f'SHORT blocked in TRENDING_UP (score {score}<{cfg["regime_override"]})'
        if 'trending_down' in regime and side == 'long':
            if score < cfg['regime_override']:
                return False, f'LONG blocked in TRENDING_DOWN (score {score}<{cfg["regime_override"]})'

    # GATE 1b: Context-aware RSI (soft regime gate)
    # Only allow counter-trend when RSI is genuinely extreme
    if cfg.get('context_rsi'):
        if 'trending_up' in regime:
            # Allow short only if RSI truly overbought (>70) or score very high
            if side == 'short' and r14 < 70 and score < cfg.get('rsi_override', 70):
                return False, f'SHORT in TRENDING_UP needs RSI>70 (got {r14:.0f})'
            # Allow long with less strict RSI (it\'s the trend direction)
            if side == 'long' and r14 > 60 and score < cfg.get('rsi_override', 70):
                return False, f'LONG in TRENDING_UP: RSI {r14:.0f}>60 without high score'
        if 'trending_down' in regime:
            if side == 'long' and r14 > 30 and score < cfg.get('rsi_override', 70):
                return False, f'LONG in TRENDING_DOWN needs RSI<30 (got {r14:.0f})'

    # GATE 2: RSI gate (base)
    if cfg.get('rsi_gate') and not cfg.get('context_rsi'):
        if side == 'long' and r14 >= cfg['rsi_long_max']:
            if score < cfg['rsi_override']:
                return False, f'LONG RSI too high ({r14:.0f})'
        if side == 'short' and r14 <= cfg['rsi_short_min']:
            if score < cfg['rsi_override']:
                return False, f'SHORT RSI too low ({r14:.0f})'

    # GATE 4: News quality floor
    if cfg.get('news_gate'):
        base_score = coin.get('long_score_base' if side == 'long' else 'short_score_base', score)
        if base_score < cfg['news_base_min'] and score > base_score + 10:
            return False, f'News inflated score: base={base_score}'

    return True, 'OK'

# ════════════════════════════════════════════════
# BACKTEST ENGINE
# ════════════════════════════════════════════════
def backtest(data, use_v11=False, label="", gate_cfg=None):
    balance = CAPITAL
    positions = {}
    trades = []
    sl_bans = {}     # {symbol: (ban_until_ts, strike_count)}
    sl_strikes = {}  # {symbol: count}
    rejections = {'regime': 0, 'rsi': 0, 'atr': 0, 'sl_ban': 0, 'news': 0}
    cfg = gate_cfg or {}


    all_ts = sorted(set(ts for sym in data for ts in data[sym]['1h'].index))[50:]

    for ts in all_ts:
        # ── CHECK EXITS ──
        for sym in list(positions.keys()):
            if sym not in data: continue
            df = data[sym]['1h']
            if ts not in df.index: continue
            pos = positions[sym]
            price = float(df.loc[ts, 'close'])
            side = pos['side']

            pnl_pct = (price/pos['entry']-1)*100 if side=='long' else (pos['entry']/price-1)*100
            if side == 'long':
                if price > pos['peak']: pos['peak'] = price
            else:
                if price < pos['peak']: pos['peak'] = price

            trail_dist = max(ATR_TRAIL_MIN/100, pos['atr_pct']/100*ATR_TRAIL_MULT)
            if not pos['trailing'] and pnl_pct >= TRAILING_TRIGGER:
                pos['trailing'] = True
                pos['sl'] = pos['entry'] * (1.001 if side=='long' else 0.999)
            if pos['trailing']:
                if side == 'long':
                    ns = pos['peak']*(1-trail_dist)
                    if ns > pos['sl']: pos['sl'] = ns
                else:
                    ns = pos['peak']*(1+trail_dist)
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
                    'pnl': pnl_usd, 'pnl_pct': pnl_pct,
                    'regime': pos.get('regime', 'unknown'),
                    'entry_score': pos.get('entry_score', 0),
                })

                # V11 Gate 3: persist SL strikes properly
                if reason == 'SL':
                    sl_strikes[sym] = sl_strikes.get(sym, 0) + 1
                    if sl_strikes[sym] >= 2:
                        ban_until = datetime.utcnow().timestamp() + 2 * 3600
                        sl_bans[sym] = (ban_until, sl_strikes[sym])
                else:
                    sl_strikes.pop(sym, None)  # Reset on non-SL exit

                del positions[sym]

        if len(positions) >= MAX_POSITIONS or balance < 5: continue

        # ── DETECT REGIME ──
        regime = 'unknown'
        if 'BTC/USDT' in data:
            btc4 = data['BTC/USDT']['4h']
            mask = btc4.index <= ts
            if mask.sum() >= 50:
                regime, _ = detect_regime(btc4.loc[mask])

        # ── BTC CRASH FILTER ──
        btc_crash = False
        if 'BTC/USDT' in data:
            btc1 = data['BTC/USDT']['1h']
            if ts in btc1.index:
                idx = btc1.index.get_loc(ts)
                if idx > 24:
                    chg = (float(btc1['close'].iloc[idx]) / float(btc1['close'].iloc[idx-24]) - 1) * 100
                    if chg < -3: btc_crash = True

        # ── REGIME THRESHOLDS ──
        base_min = 55
        if 'ranging' in regime:
            long_min, short_min = 65, 65
            min_dims_entry = 4
        elif 'trending_up' in regime:
            long_min, short_min = 50, 65
            min_dims_entry = MIN_DIMS
            if use_v11:
                long_min, short_min = 50, 65  # V11 blocks shorts fully below override
        elif 'trending_down' in regime:
            long_min, short_min = 65, 50
            min_dims_entry = MIN_DIMS
        else:
            long_min, short_min = base_min, base_min
            min_dims_entry = MIN_DIMS

        # ── SCAN + ENTER ──
        candidates = []
        for sym, d in data.items():
            if sym == 'BTC/USDT': continue
            if sym in positions: continue
            df = d['1h']
            if ts not in df.index: continue
            idx = df.index.get_loc(ts)
            if idx < 50: continue
            window = df.iloc[:idx+1]
            a = analyze(window, sym)
            if a: candidates.append(a)

        candidates.sort(key=lambda x: -x['score'])

        entered = False
        for coin in candidates:
            if len(positions) >= MAX_POSITIONS: break
            sym = coin['symbol']
            if sym in positions: continue
            ls = coin['long_score']; ss = coin['short_score']
            ld = coin['long_dims']; sd = coin['short_dims']
            ema = coin.get('ema_trend', 'neutral')
            atr_pct = coin.get('atr_pct', 2.0)
            r14 = coin.get('rsi_14', 50)

            # LONG attempt
            ema_ok = ema == 'bullish' or ls >= 70
            if ls >= long_min and ema_ok and ld >= min_dims_entry and not btc_crash:
                if use_v11:
                    ok, reason = apply_v11_gates(coin, 'long', regime, sl_bans, sym, cfg)
                    if not ok:
                        key = 'regime' if 'TRENDING' in reason else 'rsi' if 'RSI' in reason else 'atr' if 'toxic' in reason else 'sl_ban' if 'ban' in reason else 'news'
                        rejections[key] += 1
                    # ok is already True/False from gate
                else:
                    ok = True
                if ok:
                    sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct*ATR_SL_MULT))
                    tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct*ATR_TP_MULT))
                    amt = min(CAPITAL/MAX_POSITIONS, balance*0.33)
                    if amt >= 3:
                        fee = amt * FEE_PCT / 100
                        balance -= amt
                        p = coin['price']
                        positions[sym] = {
                            'side':'long','entry':p,'amount':amt-fee,
                            'tp':p*(1+tp_pct/100),'sl':p*(1-sl_pct/100),
                            'peak':p,'trailing':False,'atr_pct':atr_pct,
                            'entry_ts':ts,'regime':regime,'entry_score':ls,
                        }
                        continue

            # SHORT attempt
            ema_ok = ema == 'bearish' or ss >= 70
            if ss >= short_min and ema_ok and sd >= min_dims_entry:
                if use_v11:
                    ok, reason = apply_v11_gates(coin, 'short', regime, sl_bans, sym, cfg)
                    if not ok:
                        key = 'regime' if 'TRENDING' in reason else 'rsi' if 'RSI' in reason else 'atr' if 'toxic' in reason else 'sl_ban' if 'ban' in reason else 'news'
                        rejections[key] += 1
                    # ok is already True/False from gate
                else:
                    ok = True
                if ok:
                    sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct*ATR_SL_MULT))
                    tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct*ATR_TP_MULT))
                    amt = min(CAPITAL/MAX_POSITIONS, balance*0.33)
                    if amt >= 3:
                        fee = amt * FEE_PCT / 100
                        balance -= amt
                        p = coin['price']
                        positions[sym] = {
                            'side':'short','entry':p,'amount':amt-fee,
                            'tp':p*(1-tp_pct/100),'sl':p*(1+sl_pct/100),
                            'peak':p,'trailing':False,'atr_pct':atr_pct,
                            'entry_ts':ts,'regime':regime,'entry_score':ss,
                        }

    # ── CLOSE REMAINING ──
    for sym, pos in positions.items():
        if sym not in data: continue
        price = float(data[sym]['1h']['close'].iloc[-1])
        side = pos['side']
        pnl_pct = (price/pos['entry']-1)*100 if side=='long' else (pos['entry']/price-1)*100
        pnl_usd = pos['amount'] * pnl_pct / 100
        balance += pos['amount'] + pnl_usd
        trades.append({'symbol':sym,'side':side,'reason':'END',
                       'pnl':pnl_usd,'pnl_pct':pnl_pct,'regime':pos.get('regime','?')})

    # ── RESULTS ──
    wins = sum(1 for t in trades if t['pnl'] > 0)
    losses = len(trades) - wins
    total_pnl = sum(t['pnl'] for t in trades)
    wr = wins/len(trades)*100 if trades else 0
    w_pct = [t['pnl_pct'] for t in trades if t['pnl'] > 0]
    l_pct = [t['pnl_pct'] for t in trades if t['pnl'] <= 0]
    avg_w = np.mean(w_pct) if w_pct else 0
    avg_l = np.mean(l_pct) if l_pct else 0
    gross_w = sum(t['pnl'] for t in trades if t['pnl']>0)
    gross_l = sum(t['pnl'] for t in trades if t['pnl']<0)
    pf = abs(gross_w/gross_l) if gross_l else float('inf')

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Trades: {len(trades)} | W:{wins} L:{losses} | WR: {wr:.1f}%")
    print(f"  PnL: ${total_pnl:+.4f}  Balance: ${balance:.2f}")
    print(f"  Avg Win: {avg_w:+.1f}%  Avg Loss: {avg_l:+.1f}%  PF: {pf:.2f}")
    longs  = [t for t in trades if t['side']=='long']
    shorts = [t for t in trades if t['side']=='short']
    lw = sum(1 for t in longs if t['pnl']>0)
    sw = sum(1 for t in shorts if t['pnl']>0)
    print(f"  LONGs:  {len(longs):>3} WR:{lw/len(longs)*100:.0f}%" if longs else "  LONGs:  0")
    print(f"  SHORTs: {len(shorts):>3} WR:{sw/len(shorts)*100:.0f}%" if shorts else "  SHORTs: 0")

    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons: reasons[r] = {'n':0,'pnl':0,'w':0}
        reasons[r]['n']+=1; reasons[r]['pnl']+=t['pnl']
        if t['pnl']>0: reasons[r]['w']+=1
    print(f"  {'Reason':<10} {'N':>4} {'WR':>6} {'PnL':>10}")
    for r, d in sorted(reasons.items(), key=lambda x:-x[1]['n']):
        rwr = d['w']/d['n']*100 if d['n'] else 0
        print(f"  {r:<10} {d['n']:>4} {rwr:>5.0f}% ${d['pnl']:>+8.4f}")

    if use_v11 and any(v > 0 for v in rejections.values()):
        print(f"\n  GATES FIRED:")
        for gate, count in rejections.items():
            if count > 0:
                print(f"    {gate:<10}: {count} rejections")

    return {'trades':len(trades),'wr':wr,'pnl':total_pnl,'balance':balance}


# ════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════
if __name__ == '__main__':
    print("V11 LAB — 4-way gate calibration")
    print(f"   {len(COINS)} coins x {DAYS} days\n")
    print("Downloading...")
    data = download_data(COINS, DAYS)
    print(f"OK {len(data)} coins\n")

    # V10 baseline
    r1 = backtest(data, use_v11=False, label="V10 BASELINE")

    # V11a: Hard regime block (score<75 blocks all counter-trend)
    cfg_a = {
        'regime_lock': True, 'regime_override': 75,
        'rsi_gate': True, 'rsi_long_max': 50, 'rsi_short_min': 50, 'rsi_override': 70,
        'news_gate': False, 'news_base_min': 25, 'atr_max': 20.0,
    }
    r2 = backtest(data, use_v11=True, label="V11a: Hard regime block", gate_cfg=cfg_a)

    # V11b: Context-aware RSI
    # In trending_up: shorts need RSI>70 (true overbought), longs need RSI<45
    # In trending_down: longs need RSI<30 (true oversold), shorts need RSI>55
    # This preserves counter-trend trades at RSI extremes while blocking weak ones
    cfg_b = {
        'regime_lock': False, 'regime_override': 75,  # No hard block
        'rsi_gate': True,
        'rsi_long_max': 50, 'rsi_short_min': 50,      # Base RSI gate
        'rsi_override': 70,                             # Score override
        'news_gate': False, 'news_base_min': 25, 'atr_max': 20.0,
        'context_rsi': True,  # Use context-aware thresholds
    }
    r3 = backtest(data, use_v11=True, label="V11b: Context RSI (soft gate)", gate_cfg=cfg_b)

    # V11c: All gates, best calibration found
    cfg_c = {
        'regime_lock': True, 'regime_override': 68,   # Lower override: 68 instead of 75
        'rsi_gate': True, 'rsi_long_max': 50, 'rsi_short_min': 50, 'rsi_override': 68,
        'news_gate': True, 'news_base_min': 30, 'atr_max': 12.0,
        'context_rsi': False,
    }
    r4 = backtest(data, use_v11=True, label="V11c: Tuned gates (override=68)", gate_cfg=cfg_c)

    print(f"\n{'='*70}")
    print(f"  COMPARISON")
    print(f"{'='*70}")
    print(f"  {'Metric':<22} {'V10':>10} {'V11a':>10} {'V11b':>10} {'V11c':>10}")
    print(f"  {'Trades':<22} {r1['trades']:>10} {r2['trades']:>10} {r3['trades']:>10} {r4['trades']:>10}")
    print(f"  {'Win Rate':<22} {r1['wr']:>9.1f}% {r2['wr']:>9.1f}% {r3['wr']:>9.1f}% {r4['wr']:>9.1f}%")
    print(f"  {'PnL':<22} ${r1['pnl']:>+8.4f} ${r2['pnl']:>+8.4f} ${r3['pnl']:>+8.4f} ${r4['pnl']:>+8.4f}")
    print(f"  {'Balance':<22} ${r1['balance']:>8.2f} ${r2['balance']:>8.2f} ${r3['balance']:>8.2f} ${r4['balance']:>8.2f}")

    best = max([('V10',r1),('V11a',r2),('V11b',r3),('V11c',r4)], key=lambda x: x[1]['pnl'])
    print(f"\n  Winner: {best[0]} (PnL ${best[1]['pnl']:+.4f})")

