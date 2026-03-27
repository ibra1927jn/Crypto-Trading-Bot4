import paramiko
import json
import sys

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

output = []

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

# 1. Check running processes
output.append("=" * 60)
output.append("RUNNING PYTHON PROCESSES")
output.append("=" * 60)
_, out, _ = ssh.exec_command("ps aux | grep python | grep -v grep")
output.append(out.read().decode())

# 2. Check .env on server
output.append("=" * 60)
output.append("SERVER .ENV (TRADING_MODE)")
output.append("=" * 60)
_, out, _ = ssh.exec_command("grep -i 'mode\|paper\|capital' /opt/ct4/.env")
output.append(out.read().decode())

# 3. Last 80 lines of monitor log
output.append("=" * 60)
output.append("LAST 80 LINES OF MONITOR LOG")
output.append("=" * 60)
_, out, _ = ssh.exec_command("tail -n 80 /opt/ct4/logs/monitor.log")
log_data = out.read().decode("utf-8", errors="replace")
output.append(log_data)

# 4. Trader state
output.append("=" * 60)
output.append("TRADER STATE")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/trader_state.json 2>/dev/null || echo 'NO STATE FILE'")
state_raw = out.read().decode("utf-8", errors="replace")
try:
    state = json.loads(state_raw)
    output.append(json.dumps(state, indent=2, default=str))
except:
    output.append(state_raw)

# 5. Check SL bans
output.append("=" * 60)
output.append("SL BANS FILE")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/sl_bans.json 2>/dev/null || echo 'NO BANS FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

# 6. Recent trades
output.append("=" * 60)
output.append("LAST 10 TRADES (CSV)")
output.append("=" * 60)
_, out, _ = ssh.exec_command("tail -n 10 /opt/ct4/logs/trades.csv 2>/dev/null || echo 'NO TRADES FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

# 7. Kill switch / daily loss
output.append("=" * 60)
output.append("KILL SWITCH STATUS")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/kill_switch.json 2>/dev/null || echo 'NO KILL SWITCH FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

ssh.close()

# Write to file
with open("server_diag.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
