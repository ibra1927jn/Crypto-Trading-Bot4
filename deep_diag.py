import paramiko
import time

host = '95.217.158.7'
user = 'root'
password = 'tji3MtHJa9J4'

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)
    
    # 1. Check if monitor_server is running
    print("=== PROCESOS ACTIVOS ===")
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep python | grep -v grep")
    print(stdout.read().decode())
    
    # 2. Check last 30 lines of the log for errors
    print("=== ULTIMAS 30 LINEAS DEL LOG ===")
    stdin, stdout, stderr = ssh.exec_command("tail -n 30 /opt/ct4/logs/monitor.log")
    print(stdout.read().decode())
    
    # 3. Check the .env file to confirm our changes took effect
    print("=== CONTENIDO DEL .ENV (PAPER/CAPITAL) ===")
    stdin, stdout, stderr = ssh.exec_command("grep -E 'PAPER|CAPITAL|TRADING_MODE' /opt/ct4/.env")
    print(stdout.read().decode())
    
    # 4. Try running the bot in foreground for 5 seconds to capture startup errors
    print("=== INTENTO DE ARRANQUE EN FOREGROUND (5 seg) ===")
    stdin, stdout, stderr = ssh.exec_command("cd /opt/ct4 && timeout 8 venv/bin/python -u monitor_server.py 2>&1")
    print(stdout.read().decode())
    print(stderr.read().decode())

    ssh.close()
except Exception as e:
    print("Error:", e)
