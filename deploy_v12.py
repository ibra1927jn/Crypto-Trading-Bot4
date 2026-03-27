"""Deploy V12 Shadow Bot to Hetzner server.

Kills ALL existing V12 processes, uploads the fixed code, starts a single
clean instance, and verifies it is running.
"""
import paramiko
import os
import time

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOCAL_FILE = os.path.join(BASE_DIR, "v12_shadow_bot.py")
REMOTE_FILE = "/opt/ct4/v12_shadow_bot.py"

print(f"[1/5] Connecting to {HOST}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    ssh.connect(HOST, username=USER, password=PASS, timeout=15)
    print("      Connected!")

    # Step 2: Kill ALL v12 processes
    print("[2/5] Killing ALL v12_shadow_bot processes...")
    ssh.exec_command("pkill -f v12_shadow_bot.py")
    time.sleep(3)
    _, out, _ = ssh.exec_command("pgrep -af v12_shadow_bot || echo 'All killed'")
    result = out.read().decode().strip()
    print(f"      {result}")

    # Step 3: Upload fixed code
    print("[3/5] Uploading v12_shadow_bot.py...")
    sftp = ssh.open_sftp()
    sftp.put(LOCAL_FILE, REMOTE_FILE)
    sftp.close()
    print("      Uploaded!")

    # Ensure state directory exists
    ssh.exec_command("mkdir -p /opt/ct4/state")
    time.sleep(1)

    # Step 4: Start single clean instance
    print("[4/5] Starting V12 Shadow Bot (single instance)...")
    # Clear old log to start fresh
    ssh.exec_command("echo '' > /opt/ct4/logs/v12_shadow.log")
    time.sleep(1)
    ssh.exec_command(
        "cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py "
        "</dev/null >> logs/v12_shadow.log 2>&1 &"
    )
    time.sleep(8)

    # Step 5: Verify
    print("[5/5] Verifying...")

    # Check process
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

    # Check log output
    _, out, _ = ssh.exec_command("tail -30 /opt/ct4/logs/v12_shadow.log")
    logs = out.read().decode('utf-8', errors='replace').strip()
    print(f"\n      Last logs:\n{'=' * 50}")
    for line in logs.split('\n'):
        print(f"      {line}")
    print('=' * 50)

    # Check state file
    _, out, _ = ssh.exec_command("ls -la /opt/ct4/state/v12_paper_state.json 2>/dev/null || echo 'No state yet'")
    print(f"      State: {out.read().decode().strip()}")

except Exception as e:
    print(f"ERROR: {e}")
finally:
    ssh.close()
    print("\nDone!")
