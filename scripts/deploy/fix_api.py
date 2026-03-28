"""Kill old monitor and start new dashboard API on port 8080."""
import os
import sys
import time

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

# 1. Buscar y matar TODO en puerto 8080
print("[1] Killing ALL processes on port 8080...")
_, o, _ = ssh.exec_command('ss -tlnp | grep 8080')
print("    Before:", o.read().decode().strip())

ssh.exec_command('fuser -k 8080/tcp 2>/dev/null')
ssh.exec_command('pkill -9 -f monitor_server.py')
ssh.exec_command('pkill -9 -f api_dashboard.py')
time.sleep(3)

_, o, _ = ssh.exec_command('ss -tlnp | grep 8080')
after = o.read().decode().strip()
print("    After:", after or "Port free!")

# 2. Iniciar nueva API
print("[2] Starting api_dashboard.py...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u api_dashboard.py '
    '</dev/null >> logs/api_dashboard.log 2>&1 &'
)
time.sleep(5)

# 3. Verificar
_, o, _ = ssh.exec_command('ss -tlnp | grep 8080')
print("[3] Port 8080:", o.read().decode().strip())

_, o, _ = ssh.exec_command('pgrep -af api_dashboard')
print("    Process:", o.read().decode().strip())

# 4. Verificar log API
_, o, _ = ssh.exec_command('tail -5 /opt/ct4/logs/api_dashboard.log')
print("[4] API log:", o.read().decode().strip())

ssh.close()
print("\nDone!")
