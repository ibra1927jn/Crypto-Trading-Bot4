"""Reset V14 kill switch and restart alongside V15."""
import os
import sys
import json
import time

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

# 1. Resetear estado V14
new_state = {
    "balance": 1000.0, "equity": 1000.0, "positions": {},
    "sl_bans": {}, "peak_balance": 1000.0,
    "daily_start_balance": 1000.0, "daily_start_date": "2026-03-24",
    "total_trades": 0, "wins": 0,
    "kill_switch_active": False, "kill_switch_reason": ""
}
sftp = ssh.open_sftp()
with sftp.file('/opt/ct4/state/v12_paper_state.json', 'w') as f:
    f.write(json.dumps(new_state, indent=2))
sftp.close()
print("[1] V14 state reset to fresh $1000")

# 2. Limpiar log
ssh.exec_command('echo "" > /opt/ct4/logs/v12_shadow.log')
print("[2] V14 log cleared")

# 3. Iniciar V14
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py '
    '</dev/null >> logs/v12_shadow.log 2>&1 &'
)
print("[3] V14 bot started")
time.sleep(12)

# 4. Verificar procesos
_, o, _ = ssh.exec_command('ps aux | grep python | grep -v grep')
procs = o.read().decode().strip()
print(f"\n[4] Python processes:\n{procs}")

# 5. Log V14
_, o, _ = ssh.exec_command('tail -10 /opt/ct4/logs/v12_shadow.log')
print(f"\n[5] V14 log:\n{o.read().decode().strip()}")

# 6. Estado V15
_, o, _ = ssh.exec_command('python3 -c "import json; d=json.load(open(\'/opt/ct4/state/v15_scalper_state.json\')); print(f\'V15: Bal=${d[\"balance\"]:.2f} Pos={len(d[\"positions\"])} Trades={d[\"total_trades\"]} Wins={d[\"wins\"]}\')"')
print(f"\n[6] {o.read().decode().strip()}")

ssh.close()
print("\nDone! Both bots should be running.")
