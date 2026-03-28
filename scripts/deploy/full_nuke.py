"""Full nuke: kill bot, purge DBs and state, restart clean."""
import os
import sys
import time

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

try:
    ssh = get_ssh_client()

    # 1. Matar todo
    print("[*] Matando el bot V11...")
    ssh.exec_command("pkill -f monitor_server.py")
    time.sleep(2)

    # 2. Purgar TODAS las bases de datos y archivos de estado
    print("[*] Purgando TODAS las bases de datos y archivos de estado...")
    ssh.exec_command("rm -f /opt/ct4/db/bot_database.db")
    ssh.exec_command("rm -f /opt/ct4/db/ct4_monitor.db")
    ssh.exec_command("rm -f /opt/ct4/state/trader_state.json")
    ssh.exec_command("rm -f /opt/ct4/state.json")
    time.sleep(1)

    # 3. Verificar que se borraron
    _, stdout, _ = ssh.exec_command("ls -la /opt/ct4/db/ /opt/ct4/state/ 2>&1")
    print("Archivos restantes:", stdout.read().decode())

    # 4. Reiniciar bot desacoplado
    print("[*] Reiniciando V11 limpio...")
    transport = ssh.get_transport()
    channel = transport.open_session()
    channel.exec_command("bash -c 'cd /opt/ct4 && nohup venv/bin/python -u monitor_server.py </dev/null >> logs/monitor.log 2>&1 &'")
    channel.close()

    time.sleep(6)

    # 5. Verificar que esta vivo
    _, stdout, _ = ssh.exec_command("ps aux | grep monitor_server.py | grep -v grep")
    procs = stdout.read().decode()
    print("PROCESOS:", procs if procs else "(NINGUNO - El bot murio!)")

    _, stdout, _ = ssh.exec_command("tail -n 10 /opt/ct4/logs/monitor.log")
    print("LOG:\n", stdout.read().decode())

    ssh.close()
    print("[+] Operacion completada.")
except Exception as e:
    print("Error:", e)
