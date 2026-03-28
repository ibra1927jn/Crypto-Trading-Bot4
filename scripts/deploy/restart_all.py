"""Restart ALL: V14 bot, V15 bot, Dashboard API."""
import os
import sys
import time

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

print("="*50)
print("RESTARTING EVERYTHING")
print("="*50)

# 1. Matar todos los procesos bot viejos
print("\n[1] Killing old bot processes...")
ssh.exec_command("pkill -9 -f v12_shadow_bot.py; pkill -9 -f v15_scalper.py; pkill -9 -f api_dashboard.py; pkill -9 -f monitor_server.py")
time.sleep(3)

# 2. Iniciar V15 scalper
print("[2] Starting V15 Scalper...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v15_scalper.py '
    '</dev/null >> logs/v15_scalper.log 2>&1 &'
)
time.sleep(2)

# 3. Iniciar V14 shadow bot
print("[3] Starting V14 Shadow Bot...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py '
    '</dev/null >> logs/v12_shadow.log 2>&1 &'
)
time.sleep(2)

# 4. Iniciar Dashboard API en puerto 8082
print("[4] Starting Dashboard API on port 8082...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u api_dashboard.py '
    '</dev/null >> logs/api_dashboard.log 2>&1 &'
)
time.sleep(4)

# 5. Verificar procesos
print("\n[5] Running processes:")
_, o, _ = ssh.exec_command('ps aux | grep python | grep -v grep | grep -v document_consumer')
print(o.read().decode().strip())

# 6. Verificar puertos
print("\n[6] Ports:")
_, o, _ = ssh.exec_command('ss -tlnp | grep -E "808[0-9]"')
print(o.read().decode().strip())

# 7. Test API
print("\n[7] API test:")
_, o, _ = ssh.exec_command('curl -s http://localhost:8082/api/monitor | python3 -c "import sys,json; d=json.load(sys.stdin); t=d[\'trader\']; print(f\'Balance: ${t[\"balance\"]:.2f} | Positions: {len(t[\"positions\"])} | Trades: {t[\"total_trades\"]}\')"')
print(o.read().decode().strip())

# 8. Test dashboard HTML
print("\n[8] Dashboard test:")
_, o, _ = ssh.exec_command('curl -s http://localhost:8082/dashboard | head -c 100')
print(o.read().decode().strip()[:100])

ssh.close()
print(f"\n{'='*50}")
print("Dashboard and API restarted.")
print(f"{'='*50}")
