"""Reset V14 kill switch and restart alongside V15."""
import paramiko, time, json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

# 1. Reset V14 state
new_state = {
    "balance": 1000.0, "equity": 1000.0, "positions": {},
    "sl_bans": {}, "peak_balance": 1000.0,
    "daily_start_balance": 1000.0, "daily_start_date": "2026-03-24",
    "total_trades": 0, "wins": 0,
    "kill_switch_active": False, "kill_switch_reason": ""
}
sftp = ssh.open_sftp()
with sftp.file('/opt/ct4/state/v12_paper_state.json', 'w') as f:
    f.write(json.dumps(new_state, indent=2))
sftp.close()
print("[1] V14 state reset to fresh $1000")

# 2. Clear log
ssh.exec_command('echo "" > /opt/ct4/logs/v12_shadow.log')
print("[2] V14 log cleared")

# 3. Start V14
ssh.exec_command(
    'cd /opt/ct4 && NOHUP=1 nohup venv/bin/python -u v12_shadow_bot.py '
    '</dev/null >> logs/v12_shadow.log 2>&1 &'
)
print("[3] V14 bot started")
time.sleep(12)

# 4. Check both processes
_, o, _ = ssh.exec_command('ps aux | grep python | grep -v grep')
procs = o.read().decode().strip()
print(f"\n[4] Python processes:\n{procs}")

# 5. V14 log
_, o, _ = ssh.exec_command('tail -10 /opt/ct4/logs/v12_shadow.log')
print(f"\n[5] V14 log:\n{o.read().decode().strip()}")

# 6. V15 state  
_, o, _ = ssh.exec_command('python3 -c "import json; d=json.load(open(\'/opt/ct4/state/v15_scalper_state.json\')); print(f\'V15: Bal=${d[\"balance\"]:.2f} Pos={len(d[\"positions\"])} Trades={d[\"total_trades\"]} Wins={d[\"wins\"]}\')"')
print(f"\n[6] {o.read().decode().strip()}")

ssh.close()
print("\nDone! Both bots should be running.")
