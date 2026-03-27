"""Full diagnostic: bots, API, and dashboard."""
import paramiko, time, json, urllib.request

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

print("="*60)
print("1. ALL PYTHON PROCESSES")
print("="*60)
_, o, _ = ssh.exec_command('ps aux | grep python | grep -v grep')
print(o.read().decode().strip())

print("\n" + "="*60)
print("2. PORTS IN USE")
print("="*60)
_, o, _ = ssh.exec_command('ss -tlnp | grep -E "808[0-9]"')
print(o.read().decode().strip())

print("\n" + "="*60)
print("3. V14 STATE")
print("="*60)
_, o, _ = ssh.exec_command('cat /opt/ct4/state/v12_paper_state.json')
v14 = o.read().decode().strip()
d14 = json.loads(v14) if v14 else {}
print(f"  Balance: ${d14.get('balance',0):.2f}")
print(f"  Positions: {len(d14.get('positions',{}))}")
print(f"  Trades: {d14.get('total_trades',0)}")
print(f"  Kill Switch: {d14.get('kill_switch_active', False)}")
for sym, p in d14.get('positions',{}).items():
    print(f"    {sym}: {p.get('side','?')} @ {p.get('entry_price',0)}")

print("\n" + "="*60)
print("4. V15 STATE")
print("="*60)
_, o, _ = ssh.exec_command('cat /opt/ct4/state/v15_scalper_state.json')
v15 = o.read().decode().strip()
d15 = json.loads(v15) if v15 else {}
print(f"  Balance: ${d15.get('balance',0):.2f}")
print(f"  Positions: {len(d15.get('positions',{}))}")
print(f"  Trades: {d15.get('total_trades',0)}")
for sym, p in d15.get('positions',{}).items():
    print(f"    {sym}: {p.get('side','?')} @ {p.get('entry_price',0)}")

print("\n" + "="*60)
print("5. API DASHBOARD LOG (last 10 lines)")
print("="*60)
_, o, _ = ssh.exec_command('tail -10 /opt/ct4/logs/api_dashboard.log')
print(o.read().decode().strip())

print("\n" + "="*60)
print("6. V14 LOG (last 5 lines)")
print("="*60)
_, o, _ = ssh.exec_command('tail -5 /opt/ct4/logs/v12_shadow.log')
print(o.read().decode().strip())

print("\n" + "="*60)
print("7. V15 LOG (last 5 lines)")
print("="*60)
_, o, _ = ssh.exec_command('tail -5 /opt/ct4/logs/v15_scalper.log')
print(o.read().decode().strip())

print("\n" + "="*60)
print("8. DASHBOARD HTML CHECK (fetch URL in dashboard.html)")
print("="*60)
_, o, _ = ssh.exec_command("grep -o 'fetch.*api/monitor' /opt/ct4/dashboard.html")
print("  Fetch URL:", o.read().decode().strip())

print("\n" + "="*60)
print("9. LOCAL API TEST (curl localhost:8082/api/monitor)")
print("="*60)
_, o, _ = ssh.exec_command('curl -s http://localhost:8082/api/monitor | head -c 300')
print(o.read().decode().strip()[:300])

ssh.close()
print("\nDone!")
