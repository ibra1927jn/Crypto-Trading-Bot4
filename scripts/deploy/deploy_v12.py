"""Deploy V12 Shadow Bot to server.

Kills ALL existing V12 processes, uploads the fixed code, starts a single
clean instance, and verifies it is running.
"""
import os
import sys
import time

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client, HOST

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_FILE = os.path.join(BASE_DIR, "v12_shadow_bot.py")
REMOTE_FILE = "/opt/ct4/v12_shadow_bot.py"

print(f"[1/5] Connecting to {HOST}...")
ssh = get_ssh_client()
print("      Connected!")

try:
    # Matar todos los procesos v12
    print("[2/5] Killing ALL v12_shadow_bot processes...")
    ssh.exec_command("pkill -f v12_shadow_bot.py")
    time.sleep(3)
    _, out, _ = ssh.exec_command("pgrep -af v12_shadow_bot || echo 'All killed'")
    print(f"      {out.read().decode().strip()}")

    # Subir codigo
    print("[3/5] Uploading v12_shadow_bot.py...")
    sftp = ssh.open_sftp()
    sftp.put(LOCAL_FILE, REMOTE_FILE)
    sftp.close()
    print("      Uploaded!")

    # Asegurar directorio de estado
    ssh.exec_command("mkdir -p /opt/ct4/state")
    time.sleep(1)

    # Iniciar instancia limpia
    print("[4/5] Starting V12 Shadow Bot (single instance)...")
    ssh.exec_command("echo '' > /opt/ct4/logs/v12_shadow.log")
    time.sleep(1)
    ssh.exec_command(
        "cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py "
        "</dev/null >> logs/v12_shadow.log 2>&1 &"
    )
    time.sleep(8)

    # Verificar
    print("[5/5] Verifying...")
    _, out, _ = ssh.exec_command("pgrep -af v12_shadow_bot")
    procs = out.read().decode().strip()
    proc_count = len([l for l in procs.split('\n') if 'python' in l])
    print(f"      Processes running: {proc_count}")
    if proc_count == 1:
        print("      OK - exactly 1 instance running")
    elif proc_count > 1:
        print("      WARNING - multiple instances detected!")
    else:
        print("      ERROR - no process found!")

    _, out, _ = ssh.exec_command("tail -30 /opt/ct4/logs/v12_shadow.log")
    logs = out.read().decode('utf-8', errors='replace').strip()
    print(f"\n      Last logs:\n{'=' * 50}")
    for line in logs.split('\n'):
        print(f"      {line}")
    print('=' * 50)

    _, out, _ = ssh.exec_command("ls -la /opt/ct4/state/v12_paper_state.json 2>/dev/null || echo 'No state yet'")
    print(f"      State: {out.read().decode().strip()}")

except Exception as e:
    print(f"ERROR: {e}")
finally:
    ssh.close()
    print("\nDone!")
