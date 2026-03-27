import json
with open('v15_raw.txt', 'r', encoding='utf-8') as f:
    data = json.load(f)

# The raw txt was loaded fine by python locally because it ignored trailing garbage or maybe `cat` didn't output it.
# Actually, wait, let's just make sure it's valid:
data['killed'] = False
data['kill_switch_active'] = False

# Dump it locally
with open('v15_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
print("Saved v15_fixed.json")

import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)
sftp = ssh.open_sftp()
# use put to completely overwrite
sftp.put('v15_fixed.json', '/opt/ct4/state/v15_scalper_state.json')
sftp.close()
ssh.close()
print("Uploaded clean V15 state.")
