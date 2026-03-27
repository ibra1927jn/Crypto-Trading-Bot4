"""Deploy V15 Scalper to server and start it."""
import paramiko, time

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

# 1. Kill old V12 bot (stuck in kill switch anyway) and any old scalper
print("[1] Killing old processes...")
ssh.exec_command("pkill -9 -f v12_shadow_bot.py; pkill -9 -f v15_scalper.py")
time.sleep(2)

# 2. Upload scalper
print("[2] Uploading v15_scalper.py...")
sftp = ssh.open_sftp()
sftp.put('v15_scalper.py', '/opt/ct4/v15_scalper.py')
sftp.close()
print("    Uploaded!")

# 3. Reset state
print("[3] Resetting scalper state...")
ssh.exec_command("rm -f /opt/ct4/state/v15_scalper_state.json")
ssh.exec_command("echo '' > /opt/ct4/logs/v15_scalper.log")
ssh.exec_command("mkdir -p /opt/ct4/state /opt/ct4/logs")
time.sleep(1)

# 4. Start scalper
print("[4] Starting V15 Scalper...")
ssh.exec_command(
    "cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v15_scalper.py "
    "</dev/null >> logs/v15_scalper.log 2>&1 &"
)
time.sleep(15)

# 5. Verify
print("[5] Verifying...")
_, o, _ = ssh.exec_command("pgrep -af v15_scalper || echo 'NOT RUNNING'")
proc = o.read().decode().strip()
print(f"    Process: {proc}")

_, o, _ = ssh.exec_command("cat /opt/ct4/logs/v15_scalper.log")
logs = o.read().decode()

_, o, _ = ssh.exec_command("cat /opt/ct4/state/v15_scalper_state.json 2>/dev/null || echo '{}'")
state = o.read().decode().strip()

ssh.close()

lines = [l for l in logs.split('\n') if l.strip()]
print(f"    Log lines: {len(lines)}")
for line in lines[:25]:
    print(f"  {line}")
if len(lines) > 25:
    print(f"  ... ({len(lines)-25} more)")

print(f"\n    State: {state[:300]}")
print("\nDone!")
