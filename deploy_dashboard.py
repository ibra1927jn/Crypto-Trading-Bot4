"""Deploy dashboard API + HTML to server."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

print("[1] Killing old api_dashboard...")
ssh.exec_command("pkill -9 -f api_dashboard.py")
time.sleep(2)

print("[2] Uploading...")
sftp = ssh.open_sftp()
sftp.put('api_dashboard.py', '/opt/ct4/api_dashboard.py')
sftp.put('dashboard.html', '/opt/ct4/dashboard.html')
sftp.close()

print("[3] Opening firewall for port 8082...")
ssh.exec_command('ufw allow 8082/tcp 2>/dev/null; iptables -I INPUT -p tcp --dport 8082 -j ACCEPT 2>/dev/null')

print("[4] Starting API on port 8082...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u api_dashboard.py '
    '</dev/null >> logs/api_dashboard.log 2>&1 &'
)
time.sleep(4)

_, o, _ = ssh.exec_command('ss -tlnp | grep 8082')
print("[5] Port 8082:", o.read().decode().strip() or "NOT LISTENING")

_, o, _ = ssh.exec_command('tail -3 /opt/ct4/logs/api_dashboard.log')
print("[6] Log:", o.read().decode().strip())

ssh.close()
print("\nDashboard: http://95.217.158.7:8080/dashboard")
print("API: http://95.217.158.7:8082/api/monitor")
