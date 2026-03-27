"""
SPOT 5M SCALPER LAB v2 — More creative strategies
===================================================
8 nuevas estrategias SPOT LONG en 5m que NO se han probado aun.
"""

import ccxt, pandas as pd, pandas_ta as ta, numpy as np, time

COINS = ['DOGE/USDT','XRP/USDT','GALA/USDT','CHZ/USDT','FLOKI/USDT','PEPE/USDT','BONK/USDT','ADA/USDT']
CAPITAL = 30.0; MAX_POS = 3; AMT = 10.0; FEE = 0.001

def fetch(coins, days=7):
    print(f"📥 {days}d 5m data × {len(coins)} coins...")
    ex = ccxt.binance(); data = {}
    for sym in coins:
        try:
            ohlcv = ex.fetch_ohlcv(sym, '5m', limit=min(days*288, 1000))
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df['EMA_9'] = ta.ema(df['close'], 9)
            df['EMA_21'] = ta.ema(df['close'], 21)
            df['EMA_50'] = ta.ema(df['close'], 50)
            df['RSI'] = ta.rsi(df['close'], 14)
            df['RSI_7'] = ta.rsi(df['close'], 7)
            bb = ta.bbands(df['close'], 20, 2)
            if bb is not None:
                df['BBL'] = bb[[c for c in bb.columns if c.startswith('BBL')][0]]
                df['BBU'] = bb[[c for c in bb.columns if c.startswith('BBU')][0]]
                df['BBM'] = bb[[c for c in bb.columns if c.startswith('BBM')][0]]
            mc = ta.macd(df['close'], 12, 26, 9)
            if mc is not None:
                df['MACDH'] = mc[[c for c in mc.columns if c.startswith('MACDh')][0]]
                df['MACD'] = mc[[c for c in mc.columns if c.startswith('MACD_')][0]]
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], 14)
            adx = ta.adx(df['high'], df['low'], df['close'], 14)
            if adx is not None:
                df['ADX'] = adx[[c for c in adx.columns if c.startswith('ADX')][0]]
            stoch = ta.stochrsi(df['close'], 14)
            if stoch is not None:
                df['STOCH_K'] = stoch[[c for c in stoch.columns if 'K' in c.upper()][0]]
            df['VOL_SMA'] = df['volume'].rolling(20).mean()
            df['VOL_RATIO'] = df['volume'] / df['VOL_SMA'].replace(0, 1e-10)
            # Extra indicators for v2
            df['ROC_5'] = df['close'].pct_change(5) * 100
            df['ROC_12'] = df['close'].pct_change(12) * 100
            df['RANGE'] = (df['high'] - df['low']) / df['close'] * 100
            df['BODY'] = abs(df['close'] - df['open']) / df['close'] * 100
            df['IS_GREEN'] = df['close'] > df['open']
            df['GREEN_STREAK'] = 0
            streak = 0
            for i in range(len(df)):
                if df['IS_GREEN'].iloc[i]: streak += 1
                else: streak = 0
                df.iloc[i, df.columns.get_loc('GREEN_STREAK')] = streak
            df.dropna(inplace=True)
            data[sym] = df
            print(f" ✅ {sym}: {len(df)} velas")
        except Exception as e:
            print(f" ❌ {sym}: {e}")
        time.sleep(0.5)
    return data

class S:
    def __init__(s, name, tp, sl, tt=None, tp2=None):
        s.name=name; s.tp=tp; s.sl=sl; s.tt=tt; s.tp2=tp2
    def entry(s, r, p, h): return False

class VolumeSurge(S):
    """Volumen 3x + vela verde grande — alguien grande esta comprando"""
    def __init__(s): super().__init__("Volume Surge 3x + Green Candle", 1.5, 1.0, 0.8, 0.5)
    def entry(s, r, p, h):
        if r['VOL_RATIO'] > 3.0 and r['IS_GREEN'] and r['BODY'] > 0.3:
            if r['RSI'] < 65: return True
        return False

class ThreeGreenSoldiers(S):
    """3 velas verdes consecutivas + volumen creciente"""
    def __init__(s): super().__init__("3 Green Soldiers + Vol Up", 1.2, 0.8, 0.6, 0.4)
    def entry(s, r, p, h):
        if r['GREEN_STREAK'] >= 3 and r['VOL_RATIO'] > 1.3:
            if r['RSI'] < 65 and r['RSI'] > 35: return True
        return False

class MeanReversionBB(S):
    """Precio toca BB inferior y rebota (cierra dentro)"""
    def __init__(s): super().__init__("BB MeanReversion (Touch+Bounce)", 1.0, 0.8, 0.5, 0.3)
    def entry(s, r, p, h):
        if p['close'] < p['BBL'] and r['close'] > r['BBL']:
            if r['RSI'] < 40: return True
        return False

class ADXTrendEntry(S):
    """ADX alto (tendencia fuerte) + pullback a EMA9"""
    def __init__(s): super().__init__("ADX Trend + EMA9 Pullback", 1.8, 1.2, 1.0, 0.6)
    def entry(s, r, p, h):
        if r['ADX'] > 25 and r['EMA_9'] > r['EMA_21']:
            touch_ema = abs(r['close'] - r['EMA_9']) / r['close'] * 100 < 0.15
            if touch_ema and r['MACDH'] > 0: return True
        return False

class ROCReversal(S):
    """Caida rapida (ROC negativo) que empieza a revertir"""
    def __init__(s): super().__init__("ROC Reversal (Drop→Recovery)", 2.0, 1.5, 1.0, 0.5)
    def entry(s, r, p, h):
        if p['ROC_12'] < -2.0 and r['ROC_5'] > 0:
            if r['RSI'] < 40: return True
        return False

class NightScalper(S):
    """Solo opera en horas de Asia (00-08 UTC) — menos manipulacion"""
    def __init__(s): super().__init__("Night Scalper (Asia Hours)", 1.2, 0.8, 0.6, 0.4)
    def entry(s, r, p, h):
        if h < 0 or h > 8: return False
        if p['MACDH'] < 0 and r['MACDH'] > 0: return True
        return False

class DoubleBottom5m(S):
    """Doble suelo en 5m — precio toca BBL dos veces en 1h"""
    def __init__(s): super().__init__("Double Bottom 5m (2x BBL)", 2.0, 1.0, 1.0, 0.5)
    def entry(s, r, p, h):
        return False  # need lookback
    def entry_df(s, df, i):
        if i < 12: return False
        r = df.iloc[i]
        # Check if price touched BBL in last 12 candles (1h) at least twice
        window = df.iloc[max(0,i-12):i+1]
        touches = (window['low'] <= window['BBL']).sum()
        if touches >= 2 and r['close'] > r['BBL'] and r['RSI'] < 40:
            return True
        return False

class MACDVolCombo(S):
    """MACDH flip + Vol 2x + RSI < 50 — version mejorada del ganador"""
    def __init__(s): super().__init__("MACD+Vol+RSI Combo (Enhanced)", 1.5, 1.0, 0.8, 0.5)
    def entry(s, r, p, h):
        if p['MACDH'] < 0 and r['MACDH'] > 0:
            if r['VOL_RATIO'] > 2.0 and r['RSI'] < 50: return True
        return False

# --- ENGINE ---
def run(data, strat):
    ts_all = sorted(set(t for df in data.values() for t in df.index))
    bal = CAPITAL; positions = {}; trades = []
    for ts in ts_all:
        h = ts.hour
        for sym in list(positions.keys()):
            if ts not in data[sym].index: continue
            pos = positions[sym]; price = data[sym].loc[ts]['open']
            pnl_pct = (price / pos['ep'] - 1) * 100
            if price > pos['pk']: pos['pk'] = price
            if strat.tt and not pos['tr'] and pnl_pct >= strat.tt:
                pos['tr'] = True; pos['sl'] = max(pos['sl'], pos['ep'] * 1.001)
            if pos['tr'] and strat.tp2:
                ns = pos['pk'] * (1 - strat.tp2/100)
                if ns > pos['sl']: pos['sl'] = ns
            reason = None
            if price >= pos['tp']: reason = 'TP'
            elif price <= pos['sl']: reason = 'SL'
            elif (ts - pos['et']).total_seconds() > 14400: reason = 'TIMEOUT'
            if reason:
                ep = pos['tp'] if reason=='TP' else (pos['sl'] if reason=='SL' else price)
                net = pos['qty'] * ep * (1-FEE)
                pnl = net - pos['inv']
                bal += net
                ht = (ts - pos['et']).total_seconds() / 3600
                trades.append({'pnl':pnl,'win':pnl>0,'reason':reason,'hold':ht})
                del positions[sym]
        for sym, df in data.items():
            if ts not in df.index: continue
            idx = df.index.get_loc(ts)
            if idx < 2: continue
            r = df.iloc[idx]; p = df.iloc[idx-1]; price = r['close']
            if len(positions) < MAX_POS and sym not in positions:
                # Special: DoubleBottom uses df lookback
                if isinstance(strat, DoubleBottom5m):
                    ok = strat.entry_df(df, idx)
                else:
                    ok = strat.entry(r, p, h)
                if ok:
                    amt = min(AMT, bal)
                    if amt < 2: continue
                    bal -= amt; inv = amt * (1-FEE)
                    positions[sym] = {
                        'ep':price,'qty':inv/price,'inv':amt,'et':ts,
                        'tp':price*(1+strat.tp/100),'sl':price*(1-strat.sl/100),
                        'pk':price,'tr':False
                    }
    alloc = sum(p['qty']*data[s].iloc[-1]['close'] for s,p in positions.items())
    bal += alloc; pnl = bal - CAPITAL
    wins = sum(1 for t in trades if t['win'])
    wr = wins/len(trades)*100 if trades else 0
    ah = sum(t['hold'] for t in trades)/len(trades) if trades else 0
    tps = sum(1 for t in trades if t['reason']=='TP')
    sls = sum(1 for t in trades if t['reason']=='SL')
    tos = sum(1 for t in trades if t['reason']=='TIMEOUT')
    return {'pnl':pnl,'trades':len(trades),'wr':wr,'ah':ah,'tps':tps,'sls':sls,'tos':tos}

if __name__ == '__main__':
    data = fetch(COINS, 7)
    strats = [VolumeSurge(), ThreeGreenSoldiers(), MeanReversionBB(), ADXTrendEntry(),
              ROCReversal(), NightScalper(), DoubleBottom5m(), MACDVolCombo()]

    print("\n" + "="*95)
    print("⚡ CT4 — 5M SCALPER LAB v2 (NEW STRATEGIES)")
    print("="*95)
    print(f"Dataset: Last 7 days (5m) | {len(COINS)} coins | Timeout: 4h")
    print("-"*95)
    print(f"{'Estrategia':<40} | {'PnL':^8} | {'Trades':^6} | {'WR%':^6} | {'Hold':^5} | {'TP':^3} | {'SL':^3} | {'TO':^3}")
    print("-"*95)
    for s in strats:
        try:
            r = run(data, s)
            c = "🟢" if r['pnl'] > 0 else ("⚪" if r['trades'] == 0 else "🔴")
            print(f"{c} {s.name:<38} | ${r['pnl']:+6.2f} | {r['trades']:>5}  | {r['wr']:>5.1f}% | {r['ah']:>4.1f}h | {r['tps']:>2} | {r['sls']:>2} | {r['tos']:>2}")
        except Exception as e:
            print(f"❌ {s.name}: {e}")
    print("="*95)
