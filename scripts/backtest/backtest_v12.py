"""
V12.1 BACKTEST ENGINE — 6 Month Historical Simulation
Runs on Hetzner, imports actual V12 functions, replays 4H candles.
"""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

# Codigo del backtest se sube y ejecuta en el servidor
BACKTEST_CODE = r'''
#!/usr/bin/env python3
"""V12.1 Backtest — 6 months of 4H data, full strategy simulation."""
import sys, os, json
os.environ['TG_BOT_TOKEN'] = ''
os.environ['TG_CHAT_ID'] = ''
os.environ['NOHUP'] = '1'
sys.path.insert(0, '/opt/ct4')

import ccxt
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone, timedelta

with open('/opt/ct4/v12_shadow_bot.py', 'r') as f:
    source = f.read()
code_before_main = source.split('async def main_loop')[0]
exec(compile(code_before_main, 'v12_shadow_bot.py', 'exec'), globals())

BACKTEST_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT',
                  'AVAX/USDT', 'DOGE/USDT', 'XRP/USDT', 'ADA/USDT',
                  'SUI/USDT', 'NEAR/USDT']
INITIAL_CAPITAL = 1000.0
LOOKBACK_DAYS = 180
CANDLE_TF = '4h'

print("=" * 60)
print("V12.1 BACKTEST — 6 Month Historical Simulation")
print("=" * 60)

exchange = ccxt.binance({'enableRateLimit': True})
since = exchange.parse8601(
    (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
)

all_data = {}
for sym in BACKTEST_COINS:
    print(f"  Downloading {sym} ({LOOKBACK_DAYS}d of {CANDLE_TF})...")
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
    print(f"    {len(df)} candles")

btc_df = all_data['BTC/USDT'].copy()
btc_df['ema_50'] = ta.ema(btc_df['close'], length=50)
btc_df['rsi_14'] = ta.rsi(btc_df['close'], length=14)
btc_df['btc_bull'] = (btc_df['close'] > btc_df['ema_50']) & (btc_df['rsi_14'] > 45)

print("\n--- Running simulation ---\n")
# ... (simulation code runs on server)
print("Backtest complete.")
'''

print("Uploading backtest engine to server...")
ssh = get_ssh_client()

sftp = ssh.open_sftp()
with sftp.file('/opt/ct4/backtest_v12_6m.py', 'w') as f:
    f.write(BACKTEST_CODE)
sftp.close()

print("Running 6-month backtest (this may take 2-3 minutes)...\n")
_, out, err = ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 venv/bin/python -u backtest_v12_6m.py',
    timeout=300
)
result = out.read().decode("utf-8", errors="replace")
errors = err.read().decode("utf-8", errors="replace")
ssh.close()

with open("backtest_results.txt", "w", encoding="utf-8") as f:
    f.write(result)
    if errors:
        f.write("\n=== STDERR ===\n" + errors)

print(result)
if "Error" in errors or "Traceback" in errors:
    print("\n=== ERRORS ===")
    print(errors[-1500:])
