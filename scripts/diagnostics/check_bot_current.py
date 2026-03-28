"""Check current bot state: processes, logs, env, foreground test."""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

try:
    ssh = get_ssh_client()

    print("=== PROCESOS ACTIVOS ===")
    _, stdout, _ = ssh.exec_command("ps aux | grep python | grep -v grep")
    print(stdout.read().decode())

    print("=== ULTIMAS 30 LINEAS DEL LOG ===")
    _, stdout, _ = ssh.exec_command("tail -n 30 /opt/ct4/logs/monitor.log")
    print(stdout.read().decode())

    print("=== CONTENIDO DEL .ENV (PAPER/CAPITAL) ===")
    _, stdout, _ = ssh.exec_command("grep -E 'PAPER|CAPITAL|TRADING_MODE' /opt/ct4/.env")
    print(stdout.read().decode())

    print("=== INTENTO DE ARRANQUE EN FOREGROUND (5 seg) ===")
    _, stdout, stderr = ssh.exec_command("cd /opt/ct4 && timeout 8 venv/bin/python -u monitor_server.py 2>&1")
    print(stdout.read().decode())
    print(stderr.read().decode())

    ssh.close()
except Exception as e:
    print("Error:", e)
