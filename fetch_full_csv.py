import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

print("Fetching full CSV...")
_, stdout, _ = ssh.exec_command('cat /opt/ct4/logs/v15_trades.csv')
data = stdout.read().decode('utf-8')
with open('v15_remote_trades_full.csv', 'w', encoding='utf-8') as f:
    f.write(data)

ssh.close()
print("Saved to v15_remote_trades_full.csv")
