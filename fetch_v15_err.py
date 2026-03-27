import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

_, stdout, _ = ssh.exec_command('cat /opt/ct4/state/v15_scalper_state.json')
content = stdout.read().decode().strip()

with open('v15_raw.txt', 'w', encoding='utf-8') as f:
    f.write(content)
print("Saved to v15_raw.txt")
ssh.close()
