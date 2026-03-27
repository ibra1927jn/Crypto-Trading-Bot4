import paramiko, json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)

files_to_check = [
    '/opt/ct4/state/v12_paper_state.json',
    '/opt/ct4/state/v15_scalper_state.json'
]

with open('states_utf8.txt', 'w', encoding='utf-8') as out:
    out.write("--- RAW JSON STATES ---\\n")
    for f in files_to_check:
        out.write(f"\\nFile: {f}\\n")
        _, stdout, _ = ssh.exec_command(f'cat {f}')
        content = stdout.read().decode().strip()
        out.write(content + "\\n")

ssh.close()
print("Saved to states_utf8.txt")
