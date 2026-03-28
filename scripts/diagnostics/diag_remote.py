"""Remote diagnostic: processes, logs, env, foreground startup test."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

print("[*] Conectando para diagnostico...")
try:
    ssh = get_ssh_client()

    print("\n==================================")
    print("PROCESOS PYTHON ACTIVOS")
    print("==================================")
    _, stdout, _ = ssh.exec_command("ps aux | grep python | grep -v grep")
    print(stdout.read().decode())

    print("\n==================================")
    print("ULTIMAS 20 LINEAS: V12 SHADOW BOT")
    print("==================================")
    _, stdout, _ = ssh.exec_command("tail -n 20 /opt/ct4/logs/v12_shadow.log")
    logs = stdout.read().decode()
    if not logs:
        print("(El archivo shadow.log esta vacio o no existe)")
    else:
        print(logs)

    print("\n==================================")
    print("ULTIMAS 20 LINEAS: V11 MONITOR MAIN")
    print("==================================")
    _, stdout, _ = ssh.exec_command("tail -n 20 /opt/ct4/logs/monitor.log")
    logs_main = stdout.read().decode()
    if not logs_main:
        print("(El archivo monitor.log esta vacio o no existe)")
    else:
        print(logs_main)

    ssh.close()
except Exception as e:
    print(f"[-] Error de conexion: {e}")
