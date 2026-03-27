"""
SPOT BLIND TEST (WALK-FORWARD)
==============================
Prueba a ciegas de estrategias optimizadas para SPOT (LONG only).
Usa datos recientes reales (45 dias):
- In-Sample (IS): Primeros 30 dias (entrenamiento/validacion)
- Out-Of-Sample (OOS): Ultimos 15 dias (test ciego).

Las estrategias que sobreviven IS y OOS son robustas y no estan sobreoptimizadas.
"""

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from datetime import datetime, timedelta, timezone

COINS = ['DOGE/USDT', 'XRP/USDT', 'GALA/USDT', 'CHZ/USDT', 'FLOKI/USDT', 'PEPE/USDT', 'BONK/USDT', 'ADA/USDT']
CAPITAL = 30.0
MAX_POSITIONS = 3
AMOUNT_PER_TRADE = 10.0
FEE = 0.001  # 0.1%

def fetch_data(coins, days=45):
    print(f"📥 Descargando {days} dias de 1h data para {len(coins)} coins...")
    ex = ccxt.binance()
    data = {}
    for sym in coins:
        try:
            ohlcv = ex.fetch_ohlcv(sym, '1h', limit=days*24)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Indicators
            df['EMA_50'] = ta.ema(df['close'], 50)
            df['EMA_200'] = ta.ema(df['close'], 200)
            df['RSI_14'] = ta.rsi(df['close'], 14)
            
            bb = ta.bbands(df['close'], 20, 2)
            if bb is not None:
                df['BBL'] = bb[[c for c in bb.columns if c.startswith('BBL')][0]]
                df['BBU'] = bb[[c for c in bb.columns if c.startswith('BBU')][0]]
            
            mc = ta.macd(df['close'])
            if mc is not None:
                df['MACD'] = mc[[c for c in mc.columns if c.startswith('MACD_')][0]]
                df['MACDH'] = mc[[c for c in mc.columns if c.startswith('MACDh_')][0]]
            
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], 14)
            adx = ta.adx(df['high'], df['low'], df['close'], 14)
            if adx is not None:
                df['ADX'] = adx[[c for c in adx.columns if c.startswith('ADX')][0]]
            
            df.dropna(inplace=True)
            data[sym] = df
            print(f" ✅ {sym}: {len(df)} velas")
        except Exception as e:
            print(f" ❌ {sym}: {e}")
        time.sleep(0.5)
    return data

# --- ESTRATEGIAS SPOT (LONG ONLY) ---

class BaseStrategy:
    def __init__(self, name, tp, sl, trail_trigger=None, trail_pct=None):
        self.name = name
        self.tp = tp
        self.sl = sl
        self.trail_trigger = trail_trigger
        self.trail_pct = trail_pct
        
    def check_entry(self, row, prev_row, current_hour):
        return False

class V8_Baseline(BaseStrategy):
    # La actual v8: Caida fuerte + EMA trend o override
    def __init__(self):
        super().__init__("V8 (Actual Cautious)", 5.0, 3.0, 1.5, 1.0)
    def check_entry(self, row, prev_row, current_hour):
        if row['EMA_50'] < row['EMA_200']: return False
        return row['RSI_14'] < 25 and row['close'] <= row['BBL']

class V8_Hour_Filter(BaseStrategy):
    def __init__(self):
        super().__init__("V8 + Hour_Filter (04-08 UTC Skip)", 5.0, 3.0, 1.5, 1.0)
    def check_entry(self, row, prev_row, current_hour):
        if current_hour in [4,5,6,7]: return False
        if row['EMA_50'] < row['EMA_200']: return False
        return row['RSI_14'] < 25 and row['close'] <= row['BBL']

class Spot_Trend_Rider(BaseStrategy):
    # Tendencia alcista clara y RSI cruza 50 (pullback terminado)
    def __init__(self):
        super().__init__("Trend Rider (EMA50>EMA200, MACD+)", 6.0, 2.5, 2.0, 1.5)
    def check_entry(self, row, prev_row, current_hour):
        if row['EMA_50'] <= row['EMA_200']: return False
        if row['MACD'] < 0: return False
        if prev_row['RSI_14'] <= 50 and row['RSI_14'] > 50: return True
        return False

class Deep_Value_Dip(BaseStrategy):
    # Pánico total (sobreventa extrema), no importa tendencia
    def __init__(self):
        super().__init__("Deep Value Dip (RSI<15, Price<BB)", 10.0, 4.0, 3.0, 1.5)
    def check_entry(self, row, prev_row, current_hour):
        return row['RSI_14'] < 15 and row['close'] < (row['BBL'] * 0.98)

class Volatility_Breakout(BaseStrategy):
    # Rotura de bandas con ADX fuerte (momentum puro)
    def __init__(self):
        super().__init__("Vol Breakout (ADX>25, Price>BBU)", 4.0, 2.0, 1.0, 0.5)
    def check_entry(self, row, prev_row, current_hour):
        if 'ADX' not in row or row['ADX'] < 25: return False
        if prev_row['close'] <= prev_row['BBU'] and row['close'] > row['BBU']:
            if row['EMA_50'] > row['EMA_200']:
                return True
        return False

# --- ENGINE ---

def run_simulation(data, strategy, is_start, is_end, oos_start, oos_end):
    # data: dict of dfs
    # Sort all timestamps
    all_ts = set()
    for df in data.values():
        all_ts.update(df.index)
    all_ts = sorted(list(all_ts))
    
    def simulate_period(start_ts, end_ts):
        ts_range = [t for t in all_ts if start_ts <= t <= end_ts]
        balance = CAPITAL
        positions = {}
        trades = []
        peak_bal = CAPITAL
        max_dd = 0
        
        for ts in ts_range:
            current_hour = ts.hour
            # Verify exits first
            for sym in list(positions.keys()):
                if ts not in data[sym].index: continue
                row = data[sym].loc[ts]
                price = row['open'] # Assume exit on open if hit SL/TP overnight
                pos = positions[sym]
                
                # Check trailing
                pnl_pct = (price / pos['entry_price'] - 1) * 100
                if price > pos['peak_price']: pos['peak_price'] = price
                
                if strategy.trail_trigger:
                    if not pos['trailing'] and pnl_pct >= strategy.trail_trigger:
                        pos['trailing'] = True
                        pos['sl_price'] = pos['entry_price'] * 1.002 # break even
                    if pos['trailing']:
                        new_sl = pos['peak_price'] * (1 - strategy.trail_pct/100)
                        if new_sl > pos['sl_price']: pos['sl_price'] = new_sl
                        
                reason = None
                if price >= pos['tp_price']: reason = 'TP'
                elif price <= pos['sl_price']: reason = 'SL'
                # Timeout: 5d max hold
                elif (ts - pos['entry_time']).total_seconds() > 5*86400: reason = 'TIMEOUT'
                
                if reason:
                    # Close
                    exit_p = pos['tp_price'] if reason == 'TP' else (pos['sl_price'] if reason == 'SL' else price)
                    qty = pos['qty']
                    val = qty * exit_p
                    net = val * (1 - FEE)
                    pnl = net - pos['invested']
                    balance += net
                    trades.append({'sym':sym, 'pnl':pnl, 'win':pnl>0, 'reason':reason})
                    del positions[sym]
            
            # Record peak/DD
            alloc = sum([p['qty'] * data[s].loc[ts]['close'] for s, p in positions.items() if ts in data[s].index])
            eq = balance + alloc
            if eq > peak_bal: peak_bal = eq
            dd = (peak_bal - eq) / peak_bal * 100
            if dd > max_dd: max_dd = dd
            
            # Check entries
            for sym, df in data.items():
                if ts not in df.index: continue
                idx = df.index.get_loc(ts)
                if idx < 1: continue
                row = df.iloc[idx]
                prev = df.iloc[idx-1]
                price = row['close']
                
                if len(positions) < MAX_POSITIONS and sym not in positions:
                    if strategy.check_entry(row, prev, current_hour):
                        amt = min(AMOUNT_PER_TRADE, balance)
                        if amt < 2: continue
                        balance -= amt
                        inv = amt * (1 - FEE)
                        positions[sym] = {
                            'entry_price': price, 'qty': inv / price, 'invested': amt,
                            'entry_time': ts, 'tp_price': price * (1 + strategy.tp/100),
                            'sl_price': price * (1 - strategy.sl/100),
                            'peak_price': price, 'trailing': False
                        }
        
        # Close remaining
        alloc = sum([p['qty'] * data[s].iloc[-1]['close'] for s, p in positions.items()])
        balance += alloc
        pnl = balance - CAPITAL
        pnl_pct = (balance / CAPITAL - 1) * 100
        wins = sum(1 for t in trades if t['win'])
        wr = (wins / len(trades) * 100) if trades else 0
        return {'pnl':pnl, 'pnl_pct':pnl_pct, 'trades':len(trades), 'wr':wr, 'max_dd':max_dd}
    
    res_is = simulate_period(is_start, is_end)
    res_oos = simulate_period(oos_start, oos_end)
    return res_is, res_oos

if __name__ == '__main__':
    data = fetch_data(COINS, 45)
    
    # Calculate dates
    all_ts = set()
    for df in data.values(): all_ts.update(df.index)
    all_ts = sorted(list(all_ts))
    
    end_date = all_ts[-1]
    start_date = all_ts[0]
    is_end = start_date + timedelta(days=30)
    
    strategies = [V8_Baseline(), V8_Hour_Filter(), Spot_Trend_Rider(), Deep_Value_Dip(), Volatility_Breakout()]
    
    print("\n" + "="*80)
    print("📈 CT4 BLIND TEST REPORT (WALK-FORWARD)")
    print("="*80)
    print(f"Dataset: {start_date.date()} to {end_date.date()} (1h OHLCV)")
    print(f"In-Sample (IS): 30 days | Out-Of-Sample (OOS): 15 days")
    print(f"Modes: LONG ONLY | Multi-coin: {len(COINS)} pairs")
    print("-"*80)
    print(f"{'Estrategia':<35} | {'IS PnL':^10} | {'IS WR':^6} | {'OOS PnL':^10} | {'OOS WR':^6} | {'Robustez'}")
    print("-"*80)
    
    results = []
    for s in strategies:
        try:
            r_is, r_oos = run_simulation(data, s, start_date, is_end, is_end, end_date)
            # Robustez: if it made profit in both periods, and WR > 40%
            robust = "⭐⭐⭐" if (r_is['pnl'] > 0 and r_oos['pnl'] > 0 and r_oos['wr'] > 50) else ("⭐" if r_oos['pnl'] > 0 else "💀")
            
            print(f"{s.name:<35} | ${r_is['pnl']:+6.2f}    | {r_is['wr']:>4.1f}% | ${r_oos['pnl']:+6.2f}    | {r_oos['wr']:>4.1f}% | {robust}")
        except Exception as e:
            print(f"Error testing {s.name}: {e}")
    print("="*80)
