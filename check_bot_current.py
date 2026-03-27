import paramiko
import json

def check_status():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect('95.217.158.7', username='root', password='tji3MtHJa9J4', timeout=10)
        
        # Check V15 Status
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
                print(f"  - {sym} {pos['side']} at {pos['entry_price']} (PNL approx)")
        except Exception as e:
            print(f"Could not read V15 state: {e}")

        # Check V11 Status
        print("\n=== V11 MONITOR ===")
        _, stdout, _ = ssh.exec_command('tail -n 10 /opt/ct4/logs/monitor.log | grep PnL')
        v11_log = stdout.read().decode().strip()
        if v11_log:
            print(f"Last status log: {v11_log.split('\n')[-1]}")
        else:
            print("No recent PnL logs found for V11.")

        # Check Grid
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
