import paramiko
import json

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

output = []

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

# 1. V12 shadow bot logs
output.append("=" * 60)
output.append("V12 SHADOW BOT - LAST 100 LINES")
output.append("=" * 60)
_, out, _ = ssh.exec_command("tail -n 100 /opt/ct4/logs/v12_shadow.log")
output.append(out.read().decode("utf-8", errors="replace"))

# 2. V12 state
output.append("=" * 60)
output.append("V12 STATE FILES")
output.append("=" * 60)
_, out, _ = ssh.exec_command("ls -la /opt/ct4/state/ 2>/dev/null")
output.append(out.read().decode("utf-8", errors="replace"))

# 3. V12 shadow state
output.append("=" * 60)
output.append("V12 SHADOW STATE")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/v12_shadow_state.json 2>/dev/null || echo 'NO V12 STATE FILE'")
state_raw = out.read().decode("utf-8", errors="replace")
try:
    state = json.loads(state_raw)
    output.append(json.dumps(state, indent=2, default=str))
except:
    output.append(state_raw)

# 4. V12 trades
output.append("=" * 60)
output.append("V12 SHADOW TRADES (LAST 15)")
output.append("=" * 60)
_, out, _ = ssh.exec_command("tail -n 15 /opt/ct4/logs/v12_shadow_trades.csv 2>/dev/null || echo 'NO V12 TRADES FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

# 5. V12 source code header (to understand the strategy)
output.append("=" * 60)
output.append("V12 SOURCE CODE (first 80 lines)")
output.append("=" * 60)
_, out, _ = ssh.exec_command("head -n 80 /opt/ct4/v12_shadow_bot.py")
output.append(out.read().decode("utf-8", errors="replace"))

# 6. How many v12 processes
output.append("=" * 60)
output.append("V12 PROCESSES")
output.append("=" * 60)
_, out, _ = ssh.exec_command("ps aux | grep v12 | grep -v grep")
output.append(out.read().decode("utf-8", errors="replace"))

ssh.close()

with open("v12_diag.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
