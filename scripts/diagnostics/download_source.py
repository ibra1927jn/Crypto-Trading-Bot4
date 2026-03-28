"""Download monitor_server.py from remote server."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

try:
    ssh = get_ssh_client()
    sftp = ssh.open_sftp()
    sftp.get('/opt/ct4/monitor_server.py', 'monitor_server_remote.py')
    sftp.close()
    ssh.close()
    print("[+] Descargado monitor_server.py del servidor.")
except Exception as e:
    print("Error:", e)
