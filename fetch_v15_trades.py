import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

# Find any CSVs related to v15
stdin, stdout, stderr = ssh.exec_command('find /opt/ct4 -name "*v15*.csv"')
csv_files = stdout.read().decode().strip()
print(f"FOund CSV files:\n{csv_files}")

if csv_files:
    # Cat the most likely one
    main_file = csv_files.split('\n')[0]
    print(f"\nReading {main_file}...")
    _, stdout, _ = ssh.exec_command(f"head -n 2 {main_file} && echo '...' && tail -n 270 {main_file}")
    data = stdout.read().decode('utf-8')
    with open('v15_remote_trades.csv', 'w', encoding='utf-8') as f:
        f.write(data)
    print("Saved preview to v15_remote_trades.csv")

ssh.close()
