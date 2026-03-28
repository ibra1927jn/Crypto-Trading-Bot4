"""Fetch full V15 scalper trades CSV from remote server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

print("Fetching full V15 CSV from remote server...")
_, stdout, stderr = ssh.exec_command('cat /opt/ct4/logs/v15_scalper_trades.csv')
data = stdout.read().decode('utf-8')

if not data.strip():
    print("CSV file is empty or missing, checking /opt/ct4/data/v15_trades.csv ...")
    _, stdout, stderr = ssh.exec_command('cat /opt/ct4/data/v15_scalper_trades.csv')
    data = stdout.read().decode('utf-8')
    if not data.strip():
        print("Still no data. Finding any v15 csv...")
        _, stdout, stderr = ssh.exec_command('find /opt/ct4 -name "*v15*.csv"')
        files = stdout.read().decode('utf-8').strip().split('\\n')
        if files and files[0]:
            print(f"Reading {files[0]}")
            _, stdout, _ = ssh.exec_command(f"cat {files[0]}")
            data = stdout.read().decode('utf-8')

with open('v15_remote_trades_full.csv', 'w', encoding='utf-8', newline='') as f:
    f.write(data)

print(f"Saved {len(data.splitlines())} rows to v15_remote_trades_full.csv")
ssh.close()
