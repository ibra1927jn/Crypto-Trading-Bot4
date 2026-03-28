"""Check api_dashboard status on server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

# Verificar log
_, o, _ = ssh.exec_command('cat /opt/ct4/logs/api_dashboard.log')
print("API LOG:")
print(o.read().decode().strip()[-1000:])

# Verificar puerto 8081
_, o, _ = ssh.exec_command('ss -tlnp | grep 8081')
print("\nPort 8081:", o.read().decode().strip())

# Test local
_, o, e = ssh.exec_command('curl -s http://localhost:8081/api/monitor 2>&1 | head -c 200')
print("\nAPI Test:", o.read().decode().strip())
print("Error:", e.read().decode().strip()[:200])

# Verificar si aiohttp existe
_, o, _ = ssh.exec_command('/opt/ct4/venv/bin/python -c "import aiohttp; print(aiohttp.__version__)" 2>&1')
print("\naiohttp:", o.read().decode().strip())

ssh.close()
