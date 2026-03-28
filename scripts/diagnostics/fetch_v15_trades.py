"""Fetch V15 trades CSV preview from remote server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

ssh = get_ssh_client()

_, stdout, _ = ssh.exec_command('find /opt/ct4 -name "*v15*.csv"')
csv_files = stdout.read().decode().strip()
print(f"Found CSV files:\n{csv_files}")

if csv_files:
    main_file = csv_files.split('\n')[0]
    print(f"\nReading {main_file}...")
    _, stdout, _ = ssh.exec_command(f"head -n 2 {main_file} && echo '...' && tail -n 270 {main_file}")
    data = stdout.read().decode('utf-8')
    with open('v15_remote_trades.csv', 'w', encoding='utf-8') as f:
        f.write(data)
    print("Saved preview to v15_remote_trades.csv")

ssh.close()
