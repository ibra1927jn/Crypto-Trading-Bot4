"""Fix and upload clean V15 state to remote server."""
import os
import sys
import json

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

with open('v15_raw.txt', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Limpiar estado de kill switch
data['killed'] = False
data['kill_switch_active'] = False

with open('v15_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print("Saved v15_fixed.json")

ssh = get_ssh_client()
sftp = ssh.open_sftp()
sftp.put('v15_fixed.json', '/opt/ct4/state/v15_scalper_state.json')
sftp.close()
ssh.close()
print("Uploaded clean V15 state.")
