"""Check bot status: V15, V11, Grid."""
import os
import sys
import json

# Permitir imports desde la raiz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.ssh_helper import get_ssh_client


def check_status():
    ssh = get_ssh_client()
    try:
        print("=== V15 SCALPER ===")
        _, stdout, _ = ssh.exec_command('cat /opt/ct4/state/v15_scalper_state.json')
        try:
            v15_state = json.loads(stdout.read().decode())
            print(f"Balance: ${v15_state.get('balance', 0):.2f}")
            print(f"Daily PnL: ${v15_state.get('daily_pnl', 0):.2f}")
            print(f"Total Trades: {v15_state.get('total_trades', 0)}")
            print(f"Win Rate: {v15_state.get('wins', 0) / max(1, v15_state.get('total_trades', 1)) * 100:.1f}%")
            print(f"Kill Switch Active: {v15_state.get('kill_switch_active')}")
            positions = v15_state.get('positions', {})
            print(f"Open Positions: {len(positions)}")
            for sym, pos in positions.items():
                print(f"  - {sym} {pos['side']} at {pos['entry_price']}")
        except Exception as e:
            print(f"Could not read V15 state: {e}")

        print("\n=== V11 MONITOR ===")
        _, stdout, _ = ssh.exec_command('tail -n 10 /opt/ct4/logs/monitor.log | grep PnL')
        v11_log = stdout.read().decode().strip()
        if v11_log:
            print(f"Last status log: {v11_log.split(chr(10))[-1]}")
        else:
            print("No recent PnL logs found for V11.")

        print("\n=== GRID BOT ===")
        _, stdout, _ = ssh.exec_command('curl -s http://127.0.0.1:8081/api/state')
        try:
            grid_state = json.loads(stdout.read().decode())
            print(f"Status: {grid_state.get('status')}")
            print(f"Total Value: ${grid_state.get('total_value', 0):.2f}")
            print(f"Total Trades: {grid_state.get('total_trades', 0)}")
            print(f"Uptime: {grid_state.get('uptime_hours', 0):.1f} hours")
        except Exception as e:
            print(f"Could not read Grid state: {e}")
    finally:
        ssh.close()


if __name__ == '__main__':
    check_status()
