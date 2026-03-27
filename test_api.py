"""Test dashboard API from server."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

# Upload test script
TEST = '''
import json, urllib.request
try:
    r = urllib.request.urlopen("http://localhost:8080/api/monitor", timeout=5)
    d = json.loads(r.read())
    t = d.get("trader", {})
    b = d.get("bots", {})
    print("=== DASHBOARD API RESPONSE ===")
    print(f"Balance: ${t.get('balance',0):.2f}")
    print(f"Equity: ${t.get('equity',0):.2f}")
    print(f"PnL: ${t.get('total_pnl',0):.4f}")
    print(f"Trades: {t.get('total_trades',0)} | WR: {t.get('win_rate',0)}%")
    print(f"Positions: {len(t.get('positions',{}))}")
    for k,v in t.get("positions",{}).items():
        print(f"  {k}: {v.get('side','?')} @ {v.get('entry_price',0):.6f} bot={v.get('bot','?')}")
    if b:
        print(f"V14 status: {b.get('v14',{})}")
        print(f"V15 status: {b.get('v15',{})}")
    else:
        print("(no bots field - might be old monitor API)")
except Exception as e:
    print(f"ERROR: {e}")
'''

sftp = ssh.open_sftp()
with sftp.file('/tmp/test_api.py', 'w') as f:
    f.write(TEST)
sftp.close()

_, o, e = ssh.exec_command('python3 /tmp/test_api.py', timeout=10)
print(o.read().decode())
err = e.read().decode().strip()
if err:
    print("STDERR:", err[:300])

ssh.close()
