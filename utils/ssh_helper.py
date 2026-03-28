"""
Shared SSH helper — centraliza la conexion SSH al VPS.
Lee credenciales de .env (DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_PASS).
Provee run_ssh(), get_ssh_client() y get_sftp() para todos los scripts.
"""

import os
import sys
import paramiko
from dotenv import load_dotenv

# Cargar .env desde la raiz del proyecto
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_project_root, ".env"))

HOST = os.getenv("DEPLOY_HOST")
USER = os.getenv("DEPLOY_USER", "root")
SSH_KEY_PATH = os.getenv("DEPLOY_SSH_KEY")
PASS = os.getenv("DEPLOY_PASS")


def _build_connect_kwargs() -> dict:
    """Construye kwargs para paramiko.connect con validacion."""
    if not HOST:
        sys.exit("ERROR: DEPLOY_HOST not set in .env")

    kwargs = {"hostname": HOST, "username": USER, "timeout": 10}
    if SSH_KEY_PATH:
        kwargs["key_filename"] = SSH_KEY_PATH
    elif PASS:
        kwargs["password"] = PASS
    else:
        sys.exit("ERROR: Set DEPLOY_SSH_KEY or DEPLOY_PASS in .env")
    return kwargs


def get_ssh_client() -> paramiko.SSHClient:
    """Crea y retorna un SSHClient conectado. El caller debe cerrar."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(**_build_connect_kwargs())
    return ssh


def run_ssh(command: str) -> str:
    """Ejecuta un comando remoto y retorna stdout como string."""
    ssh = get_ssh_client()
    try:
        _, stdout, _ = ssh.exec_command(command)
        return stdout.read().decode("utf-8", errors="replace").strip()
    finally:
        ssh.close()


def run_ssh_full(command: str) -> tuple:
    """Ejecuta un comando remoto y retorna (stdout, stderr) como strings."""
    ssh = get_ssh_client()
    try:
        _, stdout, stderr = ssh.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out, err
    finally:
        ssh.close()
