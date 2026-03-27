import paramiko
import sys

host = '95.217.158.7'
user = 'root'
password = 'tji3MtHJa9J4'

print("[*] Conectando a Hetzner para diagnóstico...")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)
    
    print("\n==================================")
    print("📋 PROCESOS PYTHON ACTIVOS")
    print("==================================")
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep python | grep -v grep")
    print(stdout.read().decode())
    
    print("\n==================================")
    print("🚨 ULTIMAS 20 LINEAS: V12 SHADOW BOT")
    print("==================================")
    stdin, stdout, stderr = ssh.exec_command("tail -n 20 /opt/ct4/logs/v12_shadow.log")
    logs = stdout.read().decode()
    if not logs:
        print("(El archivo shadow.log está vacío o no existe)")
    else:
        print(logs)
        
    print("\n==================================")
    print("🚨 ULTIMAS 20 LINEAS: V11 MONITOR MAIN")
    print("==================================")
    stdin, stdout, stderr = ssh.exec_command("tail -n 20 /opt/ct4/logs/monitor.log")
    logs_main = stdout.read().decode()
    if not logs_main:
        print("(El archivo monitor.log está vacío o no existe)")
    else:
        print(logs_main)

    ssh.close()

except Exception as e:
    print(f"[-] Error de conexión: {e}")
