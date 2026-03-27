#!/usr/bin/env python3
"""
api_dashboard.py — Lightweight API for CT4 Dashboard (stdlib only)
===================================================================
Reads V14 + V15 state files, merges them, serves /api/monitor.
Uses only stdlib (http.server) — no aiohttp needed.
Runs on port 8082.
"""

import os
import json
import csv
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

V14_STATE = "/opt/ct4/state/v12_paper_state.json"
V15_STATE = "/opt/ct4/state/v15_scalper_state.json"
V14_CSV   = "/opt/ct4/logs/v12_trades.csv"
V15_CSV   = "/opt/ct4/logs/v15_trades.csv"
DASHBOARD = "/opt/ct4/dashboard.html"

PORT = 8082


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def read_csv_trades(path):
    trades = []
    try:
        with open(path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    trades.append({
                        'symbol': row.get('symbol', ''),
                        'side': row.get('side', '').lower(),
                        'reason': row.get('reason', ''),
                        'entry_price': float(row.get('entry_price', 0)),
                        'exit_price': float(row.get('exit_price', 0)),
                        'pnl': float(row.get('pnl', 0)),
                        'pnl_pct': float(row.get('pnl_pct', 0)),
                        'balance': float(row.get('balance', 0)),
                        'exit_time': row.get('close_time', ''),
                        'amount': float(row.get('amount', 0)),
                    })
                except (ValueError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return trades


def build_state():
    v14 = read_json(V14_STATE)
    v15 = read_json(V15_STATE)

    positions = {}

    for sym, pos in (v14.get('positions') or {}).items():
        positions[sym] = {
            'side': pos.get('side', 'long').lower(),
            'entry_price': pos.get('entry_price', 0),
            'amount': pos.get('amount', 0),
            'tp_price': pos.get('tp', 0),
            'sl_price': pos.get('sl', 0),
            'trailing_active': pos.get('trail_stage', 0) > 0,
            'bot': 'V14',
        }

    for sym, pos in (v15.get('positions') or {}).items():
        key = sym if sym not in positions else f"{sym} (V15)"
        positions[key] = {
            'side': pos.get('side', 'long').lower(),
            'entry_price': pos.get('entry_price', 0),
            'amount': pos.get('amount', 0),
            'tp_price': pos.get('tp', 0),
            'sl_price': pos.get('sl', 0),
            'trailing_active': pos.get('trail_stage', 0) > 0,
            'bot': 'V15',
        }

    all_trades = read_csv_trades(V14_CSV) + read_csv_trades(V15_CSV)
    all_trades.sort(key=lambda t: t.get('exit_time', ''), reverse=True)

    v14_bal = v14.get('balance', 0)
    v15_bal = v15.get('balance', 0)
    total_balance = v14_bal + v15_bal
    total_invested = sum(p.get('amount', 0) for p in positions.values())
    equity = total_balance + total_invested

    total_trades = (v14.get('total_trades', 0) or 0) + (v15.get('total_trades', 0) or 0)
    total_wins = (v14.get('wins', 0) or 0) + (v15.get('wins', 0) or 0)
    win_rate = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0

    total_pnl = sum(t['pnl'] for t in all_trades)
    initial_capital = 2000.0
    pnl_pct = round(total_pnl / initial_capital * 100, 2) if initial_capital > 0 else 0

    peak = max(v14.get('peak_balance', 1000), 1000) + max(v15.get('peak_balance', 1000), 1000)
    drawdown = round((peak - equity) / peak * 100, 1) if peak > 0 else 0

    return {
        'scan_count': 0,
        'market_mode': 'DUAL BOT',
        'mode_cfg': {'label': 'V14 (4H) + V15 (15m)', 'min_score': 55},
        'fear_greed': {'value': 50},
        'CAPITAL': initial_capital,
        'trader': {
            'balance': round(total_balance, 2),
            'equity': round(equity, 2),
            'total_pnl': round(total_pnl, 4),
            'pnl_pct': pnl_pct,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'wins': total_wins,
            'max_drawdown': drawdown,
            'positions': positions,
            'history': all_trades[:50],
        },
        'coins': [],
        'bots': {
            'v14': {
                'status': 'active' if v14 else 'offline',
                'balance': v14_bal,
                'positions': len(v14.get('positions', {})),
                'trades': v14.get('total_trades', 0),
                'killed': v14.get('kill_switch_active', False),
            },
            'v15': {
                'status': 'active' if v15 else 'offline',
                'balance': v15_bal,
                'positions': len(v15.get('positions', {})),
                'trades': v15.get('total_trades', 0),
                'killed': v15.get('killed', False),
            },
        }
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/api/monitor':
            data = json.dumps(build_state())
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data.encode())

        elif path in ('/', '/dashboard'):
            if os.path.exists(DASHBOARD):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                with open(DASHBOARD, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Dashboard not found')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Silent


if __name__ == '__main__':
    print(f"Dashboard API starting on port {PORT}...")
    print(f"  /api/monitor  -> merged V14+V15 state")
    print(f"  /dashboard    -> dashboard.html")
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
