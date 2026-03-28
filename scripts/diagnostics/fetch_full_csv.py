"""Fetch full V15 trades CSV from remote server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

print("Fetching full CSV...")
_, stdout, _ = ssh.exec_command('cat /opt/ct4/logs/v15_trades.csv')
data = stdout.read().decode('utf-8')
with open('v15_remote_trades_full.csv', 'w', encoding='utf-8') as f:
    f.write(data)

ssh.close()
print("Saved to v15_remote_trades_full.csv")
