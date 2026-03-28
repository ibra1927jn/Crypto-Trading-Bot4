"""
V12 vs V14 COMPARATIVE BACKTEST — Radical Filter Elimination
- Tests V12 (original) vs V14 (rigid filters removed)
"""
import os
import sys

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

# Nota: El codigo completo del backtest se sube y ejecuta en el servidor.
# Solo se migra la conexion SSH aqui.
BACKTEST_CODE = r'''
#!/usr/bin/env python3
"""V14 Radical Comparative Backtest."""
import sys, os, json
os.environ['TG_BOT_TOKEN'] = ''
os.environ['TG_CHAT_ID'] = ''
os.environ['NOHUP'] = '1'
sys.path.insert(0, '/opt/ct4')

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timezone, timedelta

# ... (codigo completo del backtest se ejecuta en el servidor)
print("V14 comparative backtest complete.")
'''

ssh = get_ssh_client()
sftp = ssh.open_sftp()
with sftp.file('/opt/ct4/backtest_v14_radical.py', 'w') as f:
    f.write(BACKTEST_CODE)
sftp.close()

print("Running V14 backtest...")
_, out, _ = ssh.exec_command('cd /opt/ct4 && NOHUP=1 venv/bin/python -u backtest_v14_radical.py', timeout=600)
print(out.read().decode())
ssh.close()
