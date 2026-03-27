"""Restart ALL: V14 bot, V15 bot, Dashboard API."""
import paramiko, time, json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

print("="*50)
print("RESTARTING EVERYTHING")
print("="*50)

# 1. Kill all old python processes except document_consumer
print("\n[1] Killing old bot processes...")
ssh.exec_command("pkill -9 -f v12_shadow_bot.py; pkill -9 -f v15_scalper.py; pkill -9 -f api_dashboard.py; pkill -9 -f monitor_server.py")
time.sleep(3)

# 2. Start V15 scalper
print("[2] Starting V15 Scalper...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v15_scalper.py '
    '</dev/null >> logs/v15_scalper.log 2>&1 &'
)
time.sleep(2)

# 3. Start V14 shadow bot
print("[3] Starting V14 Shadow Bot...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py '
    '</dev/null >> logs/v12_shadow.log 2>&1 &'
)
time.sleep(2)

# 4. Start Dashboard API on port 8082
print("[4] Starting Dashboard API on port 8082...")
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u api_dashboard.py '
    '</dev/null >> logs/api_dashboard.log 2>&1 &'
)
time.sleep(4)

# 5. Verify all processes
print("\n[5] Running processes:")
_, o, _ = ssh.exec_command('ps aux | grep python | grep -v grep | grep -v document_consumer')
print(o.read().decode().strip())

# 6. Check ports
print("\n[6] Ports:")
_, o, _ = ssh.exec_command('ss -tlnp | grep -E "808[0-9]"')
print(o.read().decode().strip())

# 7. Test API
print("\n[7] API test:")
_, o, _ = ssh.exec_command('curl -s http://localhost:8082/api/monitor | python3 -c "import sys,json; d=json.load(sys.stdin); t=d[\'trader\']; print(f\'Balance: ${t[\"balance\"]:.2f} | Positions: {len(t[\"positions\"])} | Trades: {t[\"total_trades\"]}\')"')
print(o.read().decode().strip())

# 8. Test dashboard HTML
print("\n[8] Dashboard test:")
_, o, _ = ssh.exec_command('curl -s http://localhost:8082/dashboard | head -c 100')
print(o.read().decode().strip()[:100])

ssh.close()
print(f"\n{'='*50}")
print(f"Dashboard URL: http://95.217.158.7:8082/dashboard")
print(f"API URL: http://95.217.158.7:8082/api/monitor")
print(f"{'='*50}")
