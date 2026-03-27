"""
SPOT 5-MINUTE SCALPER LAB
==========================
Estrategias ultra-rapidas en velas de 5 minutos.
Mas ruido, pero tambien mas oportunidades de scalping.
"""

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import time

COINS = ['DOGE/USDT','XRP/USDT','GALA/USDT','CHZ/USDT','FLOKI/USDT','PEPE/USDT','BONK/USDT','ADA/USDT']
CAPITAL = 30.0
MAX_POS = 3
AMT = 10.0
FEE = 0.001

def fetch(coins, days=7):
    print(f"📥 Descargando {days}d de 5m data para {len(coins)} coins...")
    ex = ccxt.binance()
    data = {}
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
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], 14)
            adx = ta.adx(df['high'], df['low'], df['close'], 14)
            if adx is not None:
                df['ADX'] = adx[[c for c in adx.columns if c.startswith('ADX')][0]]
            # Stochastic RSI
            stoch = ta.stochrsi(df['close'], 14)
            if stoch is not None:
                df['STOCH_K'] = stoch[[c for c in stoch.columns if 'K' in c.upper()][0]]
                df['STOCH_D'] = stoch[[c for c in stoch.columns if 'D' in c.upper()][0]]
            # Volume spike
            df['VOL_SMA'] = df['volume'].rolling(20).mean()
            df['VOL_RATIO'] = df['volume'] / df['VOL_SMA'].replace(0, 1e-10)
            df.dropna(inplace=True)
            data[sym] = df
            print(f" ✅ {sym}: {len(df)} velas")
        except Exception as e:
            print(f" ❌ {sym}: {e}")
        time.sleep(0.5)
    return data

class Strat:
    def __init__(s, name, tp, sl, tt=None, tp2=None):
        s.name=name; s.tp=tp; s.sl=sl; s.tt=tt; s.tp2=tp2
    def entry(s, r, p, h): return False

class S1(Strat):
    """EMA9 Cross EMA21 — clasico cross scalp"""
    def __init__(s): super().__init__("EMA9x21 Cross (Trend)", 1.0, 0.7, 0.5, 0.3)
    def entry(s, r, p, h):
        if p['EMA_9'] <= p['EMA_21'] and r['EMA_9'] > r['EMA_21']:
            if r['RSI'] > 40 and r['RSI'] < 70: return True
        return False

class S2(Strat):
    """StochRSI Oversold + BB Touch"""
    def __init__(s): super().__init__("StochRSI Oversold + BB (Reversal)", 1.5, 1.0, 0.8, 0.5)
    def entry(s, r, p, h):
        if 'STOCH_K' not in r: return False
        if r['STOCH_K'] < 20 and r['close'] <= r['BBL'] * 1.002:
            if r['RSI'] < 35: return True
        return False

class S3(Strat):
    """MACD Histogram Flip + Volume Spike"""
    def __init__(s): super().__init__("MACD Flip + Vol Spike", 1.2, 0.8, 0.6, 0.4)
    def entry(s, r, p, h):
        if p['MACDH'] < 0 and r['MACDH'] > 0:
            if r['VOL_RATIO'] > 1.5: return True
        return False

class S4(Strat):
    """BB Squeeze Breakout — baja volatilidad luego explosion"""
    def __init__(s): super().__init__("BB Squeeze Breakout", 2.0, 1.0, 1.0, 0.5)
    def entry(s, r, p, h):
        if 'BBU' not in r or 'BBL' not in r: return False
        bb_width = (r['BBU'] - r['BBL']) / r['BBM'] * 100
        prev_width = (p['BBU'] - p['BBL']) / p['BBM'] * 100
        if prev_width < 2.0 and bb_width > 2.5:
            if r['close'] > r['BBU'] and r['ADX'] > 20: return True
        return False

class S5(Strat):
    """RSI Divergence Scalp — RSI sube mientras precio baja"""
    def __init__(s): super().__init__("RSI Divergence (Price↓ RSI↑)", 1.5, 1.0, 0.8, 0.5)
    def entry(s, r, p, h):
        if r['close'] < p['close'] and r['RSI'] > p['RSI']:
            if r['RSI'] < 40 and r['close'] <= r['BBL'] * 1.01:
                return True
        return False

class S6(Strat):
    """Momentum Burst — RSI_7 cruza 30 hacia arriba + EMA9 > EMA21"""
    def __init__(s): super().__init__("Momentum Burst (RSI7 Cross 30↑)", 1.0, 0.8, 0.5, 0.3)
    def entry(s, r, p, h):
        if p['RSI_7'] <= 30 and r['RSI_7'] > 30:
            if r['EMA_9'] > r['EMA_21']: return True
        return False

class S7(Strat):
    """Triple Confirm — EMA trend + MACD+ + StochRSI cross"""
    def __init__(s): super().__init__("Triple Confirm (EMA+MACD+Stoch)", 1.5, 1.0, 0.8, 0.5)
    def entry(s, r, p, h):
        if 'STOCH_K' not in r: return False
        ema_ok = r['EMA_9'] > r['EMA_21'] > r['EMA_50']
        macd_ok = r['MACDH'] > 0
        stoch_ok = p['STOCH_K'] < 30 and r['STOCH_K'] > 30
        return ema_ok and macd_ok and stoch_ok

class S8(Strat):
    """Aggressive Dip Buy — RSI < 20 en 5m, cualquier tendencia"""
    def __init__(s): super().__init__("Aggressive Dip (RSI<20 5m)", 2.0, 1.5, 1.0, 0.5)
    def entry(s, r, p, h):
        return r['RSI'] < 20

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
            elif (ts - pos['et']).total_seconds() > 14400: reason = 'TIMEOUT'  # 4h max
            if reason:
                ep = pos['tp'] if reason=='TP' else (pos['sl'] if reason=='SL' else price)
                net = pos['qty'] * ep * (1-FEE)
                pnl = net - pos['inv']
                bal += net
                ht = (ts - pos['et']).total_seconds() / 3600
                trades.append({'pnl':pnl,'win':pnl>0,'reason':reason,'hold':ht,'sym':sym})
                del positions[sym]
        for sym, df in data.items():
            if ts not in df.index: continue
            idx = df.index.get_loc(ts)
            if idx < 2: continue
            r = df.iloc[idx]; p = df.iloc[idx-1]; price = r['close']
            if len(positions) < MAX_POS and sym not in positions:
                if strat.entry(r, p, h):
                    amt = min(AMT, bal)
                    if amt < 2: continue
                    bal -= amt; inv = amt * (1-FEE)
                    positions[sym] = {
                        'ep':price, 'qty':inv/price, 'inv':amt, 'et':ts,
                        'tp':price*(1+strat.tp/100), 'sl':price*(1-strat.sl/100),
                        'pk':price, 'tr':False
                    }
    alloc = sum(p['qty']*data[s].iloc[-1]['close'] for s,p in positions.items())
    bal += alloc
    pnl = bal - CAPITAL
    wins = sum(1 for t in trades if t['win'])
    wr = wins/len(trades)*100 if trades else 0
    ah = sum(t['hold'] for t in trades)/len(trades) if trades else 0
    tps = sum(1 for t in trades if t['reason']=='TP')
    sls = sum(1 for t in trades if t['reason']=='SL')
    tos = sum(1 for t in trades if t['reason']=='TIMEOUT')
    return {'pnl':pnl,'trades':len(trades),'wr':wr,'ah':ah,'tps':tps,'sls':sls,'tos':tos}

if __name__ == '__main__':
    data = fetch(COINS, 7)
    strats = [S1(), S2(), S3(), S4(), S5(), S6(), S7(), S8()]
    
    print("\n" + "="*95)
    print("⚡ CT4 — 5-MINUTE SCALPER LAB (SPOT LONG ONLY)")
    print("="*95)
    print(f"Dataset: Last 7 days (5m OHLCV) | {len(COINS)} coins | Timeout: 4h max hold")
    print("-"*95)
    print(f"{'Estrategia':<38} | {'PnL':^8} | {'Trades':^6} | {'WR%':^6} | {'Hold':^5} | {'TP':^3} | {'SL':^3} | {'TO':^3}")
    print("-"*95)
    
    for s in strats:
        try:
            r = run(data, s)
            c = "🟢" if r['pnl'] > 0 else "🔴"
            print(f"{c} {s.name:<36} | ${r['pnl']:+6.2f} | {r['trades']:>5}  | {r['wr']:>5.1f}% | {r['ah']:>4.1f}h | {r['tps']:>2} | {r['sls']:>2} | {r['tos']:>2}")
        except Exception as e:
            print(f"❌ {s.name}: {e}")
    print("="*95)
