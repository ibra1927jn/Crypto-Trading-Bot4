"""Kill old monitor and start new dashboard API on port 8080."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

# 1. Find and kill EVERYTHING on port 8080
print("[1] Killing ALL processes on port 8080...")
_, o, _ = ssh.exec_command('ss -tlnp | grep 8080')
print("    Before:", o.read().decode().strip())

ssh.exec_command('fuser -k 8080/tcp 2>/dev/null')
ssh.exec_command('pkill -9 -f monitor_server.py')
ssh.exec_command('pkill -9 -f api_dashboard.py')
time.sleep(3)

_, o, _ = ssh.exec_command('ss -tlnp | grep 8080')
after = o.read().decode().strip()
print("    After:", after or "Port free!")

# 2. Start our new API
print("[2] Starting api_dashboard.py...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u api_dashboard.py '
    '</dev/null >> logs/api_dashboard.log 2>&1 &'
)
time.sleep(5)

# 3. Verify
_, o, _ = ssh.exec_command('ss -tlnp | grep 8080')
print("[3] Port 8080:", o.read().decode().strip())

_, o, _ = ssh.exec_command('pgrep -af api_dashboard')
print("    Process:", o.read().decode().strip())

# 4. Check API log
_, o, _ = ssh.exec_command('tail -5 /opt/ct4/logs/api_dashboard.log')
print("[4] API log:", o.read().decode().strip())

ssh.close()
print("\nDone!")
