"""Fetch V15 scalper state (raw) from remote server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

_, stdout, _ = ssh.exec_command('cat /opt/ct4/state/v15_scalper_state.json')
content = stdout.read().decode().strip()

with open('v15_raw.txt', 'w', encoding='utf-8') as f:
    f.write(content)
print("Saved to v15_raw.txt")
ssh.close()
