"""
🔬 V11 DIAGNOSTIC — Which trades did the regime gate block?
Prints each rejected trade candidate and its hypothetical outcome.
"""
import ccxt, pandas as pd, pandas_ta as ta, numpy as np
from datetime import datetime, timedelta

CAPITAL = 30.0; MAX_POSITIONS = 3; FEE_PCT = 0.1
ATR_SL_MULT, ATR_TP_MULT = 1.5, 2.5
ATR_SL_MIN, ATR_SL_MAX   = 1.0, 5.0
ATR_TP_MIN, ATR_TP_MAX   = 1.5, 8.0
ATR_TRAIL_MULT = 0.8; ATR_TRAIL_MIN = 0.8
TIMEOUT_HOURS = 4; TIMEOUT_MIN_GAIN = 0.5
MIN_DIMS = 3; DAYS = 14

COINS = [
    'DOGE/USDT','XRP/USDT','ADA/USDT','SOL/USDT','AVAX/USDT',
    'PEPE/USDT','FLOKI/USDT','BONK/USDT','WIF/USDT','SHIB/USDT',
    'GALA/USDT','FET/USDT','LINK/USDT','NEAR/USDT','SUI/USDT',
    'COS/USDT','NTRN/USDT','WAXP/USDT','PHA/USDT','ATOM/USDT',
    'STO/USDT','FORTH/USDT','SXT/USDT','BTC/USDT',
]

def download_data(coins, days):
    ex = ccxt.binance({'enableRateLimit': True})
    since = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    data = {}
    for sym in coins:
        try:
            print(f"  {sym}..", end=" ", flush=True)
            o1 = ex.fetch_ohlcv(sym, '1h', since=since, limit=days*24)
            o4 = ex.fetch_ohlcv(sym, '4h', since=since, limit=days*6)
            def mk(rows):
                df = pd.DataFrame(rows, columns=['ts','open','high','low','close','volume'])
                df['ts'] = pd.to_datetime(df['ts'], unit='ms')
                df.set_index('ts', inplace=True)
                return df
            data[sym] = {'1h': mk(o1), '4h': mk(o4)}
            print("OK")
        except: print("SKIP")
    return data

def detect_regime(df_4h):
    if df_4h is None or len(df_4h) < 50: return 'unknown', 0
    close = df_4h['close']
    adx = ta.adx(df_4h['high'], df_4h['low'], close, 14)
    if adx is None: return 'unknown', 0
    adx_col = [c for c in adx.columns if 'ADX' in c]
    if not adx_col: return 'unknown', 0
    adx_val = float(adx[adx_col[0]].iloc[-1])
    ema20 = ta.ema(close, 20); ema50 = ta.ema(close, 50)
    direction = 'up' if (ema20 is not None and ema50 is not None and
                         float(ema20.iloc[-1]) > float(ema50.iloc[-1])) else 'down'
    if adx_val < 20: return 'ranging', adx_val
    elif adx_val >= 25: return f'trending_{direction}', adx_val
    else: return f'weak_trend_{direction}', adx_val

def analyze(df_1h, symbol):
    if len(df_1h) < 50: return None
    df = df_1h.iloc[:-1]; close = df['close']
    price = float(df_1h['close'].iloc[-1])
    result = {'symbol': symbol, 'price': price, 'long_score': 0, 'short_score': 0,
              'long_dims': 0, 'short_dims': 0}
    h24 = df['high'].tail(24).max(); l24 = df['low'].tail(24).min(); rng = h24 - l24
    rpos = (price - l24) / rng if rng > 0 else 0.5
    pz_l, pz_s = 0, 0
    if rpos < 0.20: pz_l = 20
    elif rpos < 0.35: pz_l = 12
    if rpos > 0.80: pz_s = 20
    elif rpos > 0.65: pz_s = 12
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
    rsi = ta.rsi(close, 14)
    r14 = float(rsi.iloc[-1]) if rsi is not None and not pd.isna(rsi.iloc[-1]) else 50
    result['rsi_14'] = r14
    if r14 < 30: result['long_score'] += 20
    elif r14 < 40: result['long_score'] += 12
    if r14 > 70: result['short_score'] += 20
    elif r14 > 60: result['short_score'] += 12
    vs = df['volume'].rolling(20).mean()
    vr = float(df['volume'].iloc[-1] / vs.iloc[-1]) if vs.iloc[-1] > 0 else 1
    result['vol_ratio'] = vr
    if vr > 2.5: result['long_score'] += 15; result['short_score'] += 15
    elif vr > 1.5: result['long_score'] += 8; result['short_score'] += 8
    ema9 = ta.ema(close, 9); ema21 = ta.ema(close, 21)
    if ema9 is not None and ema21 is not None:
        e9 = float(ema9.iloc[-1]); e21 = float(ema21.iloc[-1])
        result['ema_trend'] = 'bullish' if e9 > e21 else 'bearish'
        if e9 > e21: result['long_score'] += 10
        else: result['short_score'] += 10
    else: result['ema_trend'] = 'neutral'
    mc = ta.macd(close, 12, 26, 9)
    macd_h = 0
    if mc is not None and len(mc.columns) >= 3: macd_h = float(mc[mc.columns[2]].iloc[-1])
    result['macd_hist'] = macd_h
    roc1 = float((close.iloc[-1]/close.iloc[-2]-1)*100) if len(close)>1 else 0
    chg24 = float((close.iloc[-1]/close.iloc[-24]-1)*100) if len(close)>24 else 0
    if roc1 > 2 and chg24 > 5 and vr > 1.5: result['long_score'] += 15
    if roc1 < -2 and chg24 < -5 and vr > 1.5: result['short_score'] += 15
    if not (result.get('ema_trend')=='bullish') and chg24 < -8 and roc1 > 0.5: result['short_score'] += 18
    result['change_24h'] = chg24; result['roc1'] = roc1
    atr_raw = ta.atr(df['high'], df['low'], close, 14)
    result['atr_pct'] = float(float(atr_raw.iloc[-1]) / price * 100) if atr_raw is not None and not pd.isna(atr_raw.iloc[-1]) else 2.0
    ld = sd = 0
    if result.get('ema_trend') == 'bullish': ld += 1
    if result.get('ema_trend') == 'bearish': sd += 1
    if r14 < 45 or macd_h > 0: ld += 1
    if r14 > 55 or macd_h < 0: sd += 1
    if pz_l >= 12: ld += 1
    if pz_s >= 12: sd += 1
    if vr > 1.3: ld += 1; sd += 1
    result['long_dims'] = ld; result['short_dims'] = sd
    result['score'] = max(result['long_score'], result['short_score'])
    return result

def simulate_trade(data, sym, entry_ts, side, atr_pct):
    """Simulate a trade forward from entry_ts and return hypothetical outcome."""
    df = data[sym]['1h']
    entry_idx = df.index.get_loc(entry_ts) if entry_ts in df.index else None
    if entry_idx is None or entry_idx >= len(df)-1: return None
    entry_price = float(df['close'].iloc[entry_idx])
    sl_pct = max(ATR_SL_MIN, min(ATR_SL_MAX, atr_pct * ATR_SL_MULT))
    tp_pct = max(ATR_TP_MIN, min(ATR_TP_MAX, atr_pct * ATR_TP_MULT))
    sl = entry_price * (1-sl_pct/100) if side=='long' else entry_price * (1+sl_pct/100)
    tp = entry_price * (1+tp_pct/100) if side=='long' else entry_price * (1-tp_pct/100)
    peak = entry_price
    trailing = False
    for i in range(entry_idx+1, min(entry_idx+48, len(df))):
        price = float(df['close'].iloc[i])
        pnl = (price/entry_price-1)*100 if side=='long' else (entry_price/price-1)*100
        if side == 'long':
            if price > peak: peak = price
        else:
            if price < peak: peak = price
        trail_dist = max(ATR_TRAIL_MIN/100, atr_pct/100*ATR_TRAIL_MULT)
        if not trailing and pnl >= 1.5: trailing = True
        if trailing:
            ns = peak*(1-trail_dist) if side=='long' else peak*(1+trail_dist)
            if side=='long' and ns > sl: sl = ns
            elif side=='short' and ns < sl: sl = ns
        if side == 'long':
            if price >= tp: return ('TP', pnl, i-entry_idx)
            if price <= sl: return ('TRAIL' if trailing else 'SL', pnl, i-entry_idx)
        else:
            if price <= tp: return ('TP', pnl, i-entry_idx)
            if price >= sl: return ('TRAIL' if trailing else 'SL', pnl, i-entry_idx)
        if i - entry_idx >= TIMEOUT_HOURS and pnl < TIMEOUT_MIN_GAIN:
            return ('TIMEOUT', pnl, i-entry_idx)
    return ('END', (float(df['close'].iloc[-1])/entry_price-1)*100 if side=='long' else (entry_price/float(df['close'].iloc[-1])-1)*100, 48)

if __name__ == '__main__':
    print("🔬 DIAGNOSTIC — Regime gate impact analysis")
    print("   Simulating what happens to each blocked SHORT in trending_up\n")
    data = download_data(COINS, DAYS)
    print(f"\n✅ {len(data)} coins\n")

    blocked_trades = []
    all_ts = sorted(set(ts for sym in data for ts in data[sym]['1h'].index))[50:]
    regime_cache = {}

    for ts in all_ts:
        # Detect regime (cache every 4h)
        ts_key = ts.replace(hour=ts.hour//4*4, minute=0, second=0, microsecond=0)
        if ts_key not in regime_cache:
            if 'BTC/USDT' in data:
                btc4 = data['BTC/USDT']['4h']
                mask = btc4.index <= ts
                if mask.sum() >= 50:
                    regime, adx = detect_regime(btc4.loc[mask])
                    regime_cache[ts_key] = (regime, adx)
        regime, adx = regime_cache.get(ts_key, ('unknown', 0))

        for sym, d in data.items():
            if sym == 'BTC/USDT': continue
            df = d['1h']
            if ts not in df.index: continue
            idx = df.index.get_loc(ts)
            if idx < 50: continue
            a = analyze(df.iloc[:idx+1], sym)
            if a is None: continue
            ss = a['short_score']; sd = a['short_dims']
            # Would V10 have entered this short?
            if ss >= 65 and sd >= MIN_DIMS and 'trending_up' in regime:
                # V11 would block this (score < 75)
                if ss < 75:
                    outcome = simulate_trade(data, sym, ts, 'short', a['atr_pct'])
                    if outcome:
                        blocked_trades.append({
                            'ts': ts, 'sym': sym, 'score': ss, 'dims': sd,
                            'rsi': a['rsi_14'], 'atr': a['atr_pct'],
                            'regime': regime, 'adx': adx,
                            'outcome': outcome[0], 'pnl': outcome[1], 'hours': outcome[2]
                        })

    print(f"Found {len(blocked_trades)} trades V11 would block in trending_up:")
    print(f"{'Time':<12} {'Sym':<12} {'SC':>4} {'RSI':>5} {'ATR':>5} {'Outcome':<8} {'PnL':>8} {'H':>4}")
    wins = 0
    for t in blocked_trades[:30]:
        win = '✅' if t['pnl'] > 0 else '❌'
        if t['pnl'] > 0: wins += 1
        print(f"{str(t['ts'])[:13]} {t['sym']:<12} {t['score']:>4} {t['rsi']:>5.0f} {t['atr']:>4.1f}% {t['outcome']:<8} {t['pnl']:>+7.1f}% {t['hours']:>3.0f}h {win}")
    n = len(blocked_trades)
    if n:
        print(f"\nHypothetical WR if allowed: {wins}/{n} = {wins/n*100:.1f}%")
        print(f"Avg win: {np.mean([t['pnl'] for t in blocked_trades if t['pnl']>0]):.1f}%" if wins else "")
        print(f"Avg loss: {np.mean([t['pnl'] for t in blocked_trades if t['pnl']<=0]):.1f}%" if wins < n else "")
