"""Check api_dashboard status on server."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

# Check log
_, o, _ = ssh.exec_command('cat /opt/ct4/logs/api_dashboard.log')
print("API LOG:")
print(o.read().decode().strip()[-1000:])

# Check port 8081
_, o, _ = ssh.exec_command('ss -tlnp | grep 8081')
print("\nPort 8081:", o.read().decode().strip())

# Test locally  
_, o, e = ssh.exec_command('curl -s http://localhost:8081/api/monitor 2>&1 | head -c 200')
print("\nAPI Test:", o.read().decode().strip())
print("Error:", e.read().decode().strip()[:200])

# Check if aiohttp exists
_, o, _ = ssh.exec_command('/opt/ct4/venv/bin/python -c "import aiohttp; print(aiohttp.__version__)" 2>&1')
print("\naiohttp:", o.read().decode().strip())

ssh.close()
