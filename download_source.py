import paramiko

host = '95.217.158.7'
user = 'root'
password = 'tji3MtHJa9J4'

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)
    
    # Download the full monitor_server.py to analyze the equity check
    sftp = ssh.open_sftp()
    sftp.get('/opt/ct4/monitor_server.py', 'monitor_server_remote.py')
    sftp.close()
    ssh.close()
    print("[+] Descargado monitor_server.py del servidor.")
except Exception as e:
    print("Error:", e)
