import paramiko
import time

host = '95.217.158.7'
user = 'root'
password = 'tji3MtHJa9J4'

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)

    # 1. Kill everything
    print("[*] Matando el bot V11...")
    ssh.exec_command("pkill -f monitor_server.py")
    time.sleep(2)

    # 2. Nuke ALL databases and state files
    print("[*] Purgando TODAS las bases de datos y archivos de estado...")
    ssh.exec_command("rm -f /opt/ct4/db/bot_database.db")
    ssh.exec_command("rm -f /opt/ct4/db/ct4_monitor.db")
    ssh.exec_command("rm -f /opt/ct4/state/trader_state.json")
    ssh.exec_command("rm -f /opt/ct4/state.json")
    time.sleep(1)

    # 3. Verify files are gone
    stdin, stdout, stderr = ssh.exec_command("ls -la /opt/ct4/db/ /opt/ct4/state/ 2>&1")
    print("Archivos restantes:", stdout.read().decode())

    # 4. Restart bot fully detached
    print("[*] Reiniciando V11 limpio...")
    transport = ssh.get_transport()
    channel = transport.open_session()
    channel.exec_command("bash -c 'cd /opt/ct4 && nohup venv/bin/python -u monitor_server.py </dev/null >> logs/monitor.log 2>&1 &'")
    channel.close()

    time.sleep(6)

    # 5. Check it is alive and NOT crashing
    stdin, stdout, stderr = ssh.exec_command("ps aux | grep monitor_server.py | grep -v grep")
    procs = stdout.read().decode()
    print("PROCESOS:", procs if procs else "(NINGUNO - El bot murio!)")

    stdin, stdout, stderr = ssh.exec_command("tail -n 10 /opt/ct4/logs/monitor.log")
    print("LOG:\n", stdout.read().decode())

    ssh.close()
    print("[+] Operacion completada.")
except Exception as e:
    print("Error:", e)
