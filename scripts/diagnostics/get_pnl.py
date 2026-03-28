"""Calculate PnL for V14 and V15 from remote state files."""
import os
import sys
import json

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client

try:
    import ccxt
    exchange = ccxt.binance()
    tickers = exchange.fetch_tickers()
    def get_price(sym): return tickers.get(sym, {}).get('last', 0)
except Exception:
    def get_price(sym): return 0

with open('pnl_out.txt', 'w', encoding='utf-8') as out:
    for name, path in [('V14', '/opt/ct4/state/v12_paper_state.json'), ('V15', '/opt/ct4/state/v15_scalper_state.json')]:
        ssh = get_ssh_client()
        sftp = ssh.open_sftp()
        try:
            with sftp.open(path, 'r') as f:
                data = json.load(f)
            out.write(f"\\n--- {name} PnL ---\\n")
            tot = 0
            for sym, pos in data.get('positions', {}).items():
                cp = get_price(sym)
                if cp == 0: continue
                ep = pos['entry_price']
                qty = pos['qty']
                pnl = (cp - ep) * qty if pos['side'] == 'LONG' else (ep - cp) * qty
                tot += pnl
                out.write(f"{sym} {pos['side']} @ {ep} -> {cp} | PnL: ${pnl:.2f}\\n")
            out.write(f"TOTAL {name}: ${tot:.2f}\\n")
        except Exception as e:
            out.write(f"Error {name}: {e}\\n")
        sftp.close()
        ssh.close()
