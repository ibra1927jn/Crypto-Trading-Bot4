"""Deep diagnostic: processes, env, logs, state, SL bans, trades, kill switch."""
import os
import sys
import json

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client, HOST

output = []

ssh = get_ssh_client()

output.append("=" * 60)
output.append("RUNNING PYTHON PROCESSES")
output.append("=" * 60)
_, out, _ = ssh.exec_command("ps aux | grep python | grep -v grep")
output.append(out.read().decode())

output.append("=" * 60)
output.append("SERVER .ENV (TRADING_MODE)")
output.append("=" * 60)
_, out, _ = ssh.exec_command("grep -i 'mode\\|paper\\|capital' /opt/ct4/.env")
output.append(out.read().decode())

output.append("=" * 60)
output.append("LAST 80 LINES OF MONITOR LOG")
output.append("=" * 60)
_, out, _ = ssh.exec_command("tail -n 80 /opt/ct4/logs/monitor.log")
output.append(out.read().decode("utf-8", errors="replace"))

output.append("=" * 60)
output.append("TRADER STATE")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/trader_state.json 2>/dev/null || echo 'NO STATE FILE'")
state_raw = out.read().decode("utf-8", errors="replace")
try:
    state = json.loads(state_raw)
    output.append(json.dumps(state, indent=2, default=str))
except Exception:
    output.append(state_raw)

output.append("=" * 60)
output.append("SL BANS FILE")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/sl_bans.json 2>/dev/null || echo 'NO BANS FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

output.append("=" * 60)
output.append("LAST 10 TRADES (CSV)")
output.append("=" * 60)
_, out, _ = ssh.exec_command("tail -n 10 /opt/ct4/logs/trades.csv 2>/dev/null || echo 'NO TRADES FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

output.append("=" * 60)
output.append("KILL SWITCH STATUS")
output.append("=" * 60)
_, out, _ = ssh.exec_command("cat /opt/ct4/state/kill_switch.json 2>/dev/null || echo 'NO KILL SWITCH FILE'")
output.append(out.read().decode("utf-8", errors="replace"))

ssh.close()

with open("server_diag.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
