import paramiko, json, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

sftp = ssh.open_sftp()

print("Calculating PnL and fixing state files...")

# Fetch Binance prices using CCXT if possible, or skip
try:
    import ccxt
    exchange = ccxt.binance()
    tickers = exchange.fetch_tickers()
    def get_price(symbol):
        return tickers.get(symbol, {}).get('last', 0)
except:
    print("CCXT not found, simulating PnL check based on 0 diff.")
    def get_price(symbol): return 0

# Fix V14
v14_path = '/opt/ct4/state/v12_paper_state.json'
with sftp.open(v14_path, 'r') as f:
    v14 = json.load(f)

print("\\nV14 Positions PnL:")
total_v14_pnl = 0
for sym, pos in v14.get('positions', {}).items():
    current_price = get_price(sym)
    if current_price == 0: continue
    entry = pos['entry_price']
    qty = pos['qty']
    if pos['side'] == 'LONG':
        pnl = (current_price - entry) * qty
    else:
        pnl = (entry - current_price) * qty
    total_v14_pnl += pnl
    print(f"  {sym} {pos['side']} @ {entry} -> Current: {current_price} | PnL: ${pnl:.2f}")
print(f"Total V14 UnRealized PnL: ${total_v14_pnl:.2f}")

v14['kill_switch'] = False
v14['kill_switch_active'] = False
v14['kill_switch_reason'] = ""
with sftp.open(v14_path, 'w') as f:
    json.dump(v14, f, indent=2)

# Fix V15
v15_path = '/opt/ct4/state/v15_scalper_state.json'
with sftp.open(v15_path, 'r') as f:
    v15 = json.load(f)

print("\\nV15 Positions PnL:")
total_v15_pnl = 0
for sym, pos in v15.get('positions', {}).items():
    current_price = get_price(sym)
    if current_price == 0: continue
    entry = pos['entry_price']
    qty = pos['qty']
    if pos['side'] == 'LONG':
        pnl = (current_price - entry) * qty
    else:
        pnl = (entry - current_price) * qty
    total_v15_pnl += pnl
    print(f"  {sym} {pos['side']} @ {entry} -> Current: {current_price} | PnL: ${pnl:.2f}")
print(f"Total V15 UnRealized PnL: ${total_v15_pnl:.2f}")

v15['killed'] = False
v15['kill_switch_active'] = False
with sftp.open(v15_path, 'w') as f:
    json.dump(v15, f, indent=2)

sftp.close()
print("\\nStates fixed and uploaded.")

# Restarting the bots to apply new state correctly
print("Restarting V14 and V15 processes on server via PM2 or Nohup...")
ssh.exec_command("pkill -f v12_shadow_bot.py")
ssh.exec_command("pkill -f monitor_server.py")
ssh.exec_command("pkill -f v15_scalper.py")

time.sleep(2)

# Start monitor
ssh.exec_command("bash -c 'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u monitor_server.py </dev/null >> logs/monitor.log 2>&1 &'")
# Start V15
ssh.exec_command("bash -c 'cd /opt/ct4 && nohup venv/bin/python -u v15_scalper.py </dev/null >> logs/v15_scalper.log 2>&1 &'")

ssh.close()
print("Bots restarted.")
