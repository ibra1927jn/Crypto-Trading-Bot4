"""Kill all V12 processes, restart cleanly, verify logs."""
import paramiko, time

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

# Kill ALL
print("[1] Killing all v12 processes...")
ssh.exec_command("pkill -9 -f v12_shadow_bot.py")
time.sleep(3)

# Verify killed
_, o, _ = ssh.exec_command("pgrep -af v12_shadow_bot || echo 'All killed'")
print(f"    {o.read().decode().strip()}")

# Clear log
ssh.exec_command("echo '' > /opt/ct4/logs/v12_shadow.log")
time.sleep(1)

# Start fresh with NOHUP=1
print("[2] Starting fresh...")
ssh.exec_command(
    "cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py "
    "</dev/null >> logs/v12_shadow.log 2>&1 &"
)

# Wait for first scan
print("[3] Waiting 20s for first scan...")
time.sleep(20)

# Check process count
_, o, _ = ssh.exec_command("pgrep -c -f v12_shadow_bot")
procs = o.read().decode().strip()
print(f"    Processes: {procs}")

# Read logs
_, o, _ = ssh.exec_command("cat /opt/ct4/logs/v12_shadow.log")
logs = o.read().decode("utf-8", errors="replace")
ssh.close()

# Save and display
with open("v12_phase4_logs.txt", "w", encoding="utf-8") as f:
    f.write(logs)

lines = [l for l in logs.split('\n') if l.strip()]
print(f"\n    Log lines: {len(lines)}")
print(f"    Duplicates: {'YES' if any(lines[i] == lines[i+1] for i in range(len(lines)-1)) else 'NO'}")
print()
for line in lines[:40]:
    print(f"  {line}")
if len(lines) > 40:
    print(f"  ... ({len(lines)-40} more lines)")
