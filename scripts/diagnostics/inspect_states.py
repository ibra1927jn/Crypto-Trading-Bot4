"""Inspect V14 and V15 state files from remote server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

files_to_check = [
    '/opt/ct4/state/v12_paper_state.json',
    '/opt/ct4/state/v15_scalper_state.json'
]

with open('states_utf8.txt', 'w', encoding='utf-8') as out:
    out.write("--- RAW JSON STATES ---\\n")
    for f in files_to_check:
        out.write(f"\\nFile: {f}\\n")
        _, stdout, _ = ssh.exec_command(f'cat {f}')
        content = stdout.read().decode().strip()
        out.write(content + "\\n")

ssh.close()
print("Saved to states_utf8.txt")
