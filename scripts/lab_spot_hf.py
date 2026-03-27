"""
SPOT HIGH-FREQUENCY TEST
========================
Busca estrategias para SPOT (LONG ONLY) que generen mas trades (~40)
y los mantengan por poco tiempo (Scalping).
Usa temporalidad de 15m y TPs/SLs ajustados (1.5% - 2.5%).
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

def fetch_data(coins, days=15):
    print(f"📥 Descargando {days} dias de 15m data para {len(coins)} coins...")
    ex = ccxt.binance()
    data = {}
    for sym in coins:
        try:
            ohlcv = ex.fetch_ohlcv(sym, '15m', limit=days*96)
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

# --- ESTRATEGIAS SPOT SCALPER (LONG ONLY) ---

class BaseStrategy:
    def __init__(self, name, tp, sl, trail_trigger=None, trail_pct=None):
        self.name = name
        self.tp = tp
        self.sl = sl
        self.trail_trigger = trail_trigger
        self.trail_pct = trail_pct
        
    def check_entry(self, row, prev_row, current_hour):
        return False

class Micro_Scalper(BaseStrategy):
    # RSI bajo rapido, targets cortos. No le importa la tendencia.
    def __init__(self):
        super().__init__("Micro Scalper (RSI<25 15m)", 1.5, 1.0, 0.8, 0.5)
    def check_entry(self, row, prev_row, current_hour):
        return row['RSI_14'] < 25 and row['close'] < row['BBL']

class Scalp_Trend_Rider(BaseStrategy):
    # Pullbacks en 15m con cruce de MACD a favor de tendencia.
    def __init__(self):
        super().__init__("15m Trend Rider (MACD+ in Uptrend)", 2.0, 1.5, 1.0, 0.8)
    def check_entry(self, row, prev_row, current_hour):
        if row['EMA_50'] <= row['EMA_200']: return False
        if prev_row['MACDH'] < 0 and row['MACDH'] > 0: return True
        return False

class Fast_Vol_Breakout(BaseStrategy):
    # Rompe bandas en 15m con volatilidad, scalping rapido.
    def __init__(self):
        super().__init__("Fast Breakout (ADX>30, BBU)", 2.5, 1.5, 1.5, 0.8)
    def check_entry(self, row, prev_row, current_hour):
        if 'ADX' not in row or row['ADX'] < 30: return False
        if prev_row['close'] <= prev_row['BBU'] and row['close'] > row['BBU']:
            # Solo si no esta ultra sobrecomprado
            if row['RSI_14'] < 75: return True
        return False

class V8_Aggressive(BaseStrategy):
    # Version suelta de la original para 15m (RSI<35)
    def __init__(self):
        super().__init__("V8 Aggressive (RSI<35)", 3.0, 2.0, 1.5, 1.0)
    def check_entry(self, row, prev_row, current_hour):
        if row['EMA_50'] > row['EMA_200']:
            return row['RSI_14'] < 35 and row['close'] <= row['BBL']
        return False

# --- ENGINE ---

def run_simulation(data, strategy):
    all_ts = set()
    for df in data.values():
        all_ts.update(df.index)
    all_ts = sorted(list(all_ts))
    
    balance = CAPITAL
    positions = {}
    trades = []
    
    for ts in all_ts:
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
                    pos['sl_price'] = max(pos['sl_price'], pos['entry_price'] * 1.001) # break even
                if pos['trailing']:
                    new_sl = pos['peak_price'] * (1 - strategy.trail_pct/100)
                    if new_sl > pos['sl_price']: pos['sl_price'] = new_sl
                    
            reason = None
            if price >= pos['tp_price']: reason = 'TP'
            elif price <= pos['sl_price']: reason = 'SL'
            # Timeout: 24h max hold for scalping
            elif (ts - pos['entry_time']).total_seconds() > 86400: reason = 'TIMEOUT'
            
            if reason:
                # Close
                exit_p = pos['tp_price'] if reason == 'TP' else (pos['sl_price'] if reason == 'SL' else price)
                qty = pos['qty']
                val = qty * exit_p
                net = val * (1 - FEE)
                pnl = net - pos['invested']
                balance += net
                hold_time_hours = (ts - pos['entry_time']).total_seconds() / 3600
                trades.append({'sym':sym, 'pnl':pnl, 'win':pnl>0, 'reason':reason, 'hold_hours':hold_time_hours})
                del positions[sym]
        
        # Check entries
        for sym, df in data.items():
            if ts not in df.index: continue
            idx = df.index.get_loc(ts)
            if idx < 1: continue
            row = df.iloc[idx]
            prev = df.iloc[idx-1]
            price = row['close']
            
            # Global cooldown per symbol: 1h min between trades
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
    avg_hold = sum(t['hold_hours'] for t in trades) / len(trades) if trades else 0
    
    return {'pnl':pnl, 'pnl_pct':pnl_pct, 'trades':len(trades), 'wr':wr, 'avg_hold':avg_hold}

if __name__ == '__main__':
    data = fetch_data(COINS, 15)
    
    strategies = [Micro_Scalper(), Scalp_Trend_Rider(), Fast_Vol_Breakout(), V8_Aggressive()]
    
    print("\n" + "="*85)
    print("⚡ CT4 HIGH-FREQUENCY SPOT LAB (15m SCALPING)")
    print("="*85)
    print(f"Dataset: Last 15 days (15m OHLCV)")
    print(f"Modes: LONG ONLY | Multi-coin: {len(COINS)} pairs")
    print(f"Target: ~40 trades con alta rotacion (1h - 12h hold time)")
    print("-"*85)
    print(f"{'Estrategia':<35} | {'PnL Total':^10} | {'Trades':^6} | {'WR %':^6} | {'Avg Hold (h)'}")
    print("-"*85)
    
    for s in strategies:
        try:
            r = run_simulation(data, s)
            color = "🟢" if r['pnl'] > 0 else "🔴"
            print(f"{color} {s.name:<33} | ${r['pnl']:+8.2f}  | {r['trades']:>5d}  | {r['wr']:>5.1f}% | {r['avg_hold']:>5.1f}h")
        except Exception as e:
            print(f"Error testing {s.name}: {e}")
    print("="*85)
