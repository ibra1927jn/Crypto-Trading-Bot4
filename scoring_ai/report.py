"""
report.py — Scoring AI Module
================================
Generates a human-readable HTML report summarizing the trade
history, cluster patterns, and risk distribution.

Usage:
    python report.py
    python report.py --output my_report.html
    python report.py --open   (auto-opens browser after generating)
"""

import os
import json
import argparse
import webbrowser
from datetime import datetime

DB_PATH     = os.path.join(os.path.dirname(__file__), "vector_db.json")
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "scoring_report.html")


def load_db() -> dict:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            "Vector DB not found. Run collector.py first.")
    with open(DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def risk_color(pnl_pct: float) -> str:
    if pnl_pct > 0:
        return "#27ae60"   # green
    return "#e74c3c"       # red


def generate_report(output_path: str, open_browser: bool = False):
    db = load_db()
    records = db.get("records", [])
    losers  = [r for r in records if r["outcome"] == 0]
    winners = [r for r in records if r["outcome"] == 1]

    # Aggregate by symbol
    symbol_stats: dict[str, dict] = {}
    for r in records:
        sym = r["symbol"]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"wins": 0, "losses": 0, "pnl_total": 0.0}
        if r["outcome"] == 1:
            symbol_stats[sym]["wins"] += 1
        else:
            symbol_stats[sym]["losses"] += 1
        symbol_stats[sym]["pnl_total"] += r.get("pnl_pct", 0)

    rows_html = ""
    for r in sorted(records, key=lambda x: x.get("close_time", ""), reverse=True):
        color = risk_color(r.get("pnl_pct", 0))
        outcome_label = "✅ WIN" if r["outcome"] == 1 else "❌ LOSS"
        rows_html += f"""
        <tr>
          <td>{r.get('close_time','')[:16]}</td>
          <td>{r.get('symbol','')}</td>
          <td>{r.get('side','')}</td>
          <td>{r.get('reason','')}</td>
          <td style="color:{color};font-weight:bold">{r.get('pnl_pct',0):+.2f}%</td>
          <td>{outcome_label}</td>
          <td style="font-size:0.75em;color:#888">{','.join(f'{v:.2f}' for v in r.get('vector',[]))}</td>
        </tr>"""

    sym_rows = ""
    for sym, st in sorted(symbol_stats.items()):
        total = st["wins"] + st["losses"]
        wr = st["wins"] / total * 100 if total else 0
        color = "#27ae60" if wr >= 50 else "#e74c3c"
        sym_rows += f"""
        <tr>
          <td>{sym}</td>
          <td>{total}</td>
          <td style="color:{color}">{wr:.0f}%</td>
          <td style="color:{'#27ae60' if st['pnl_total'] > 0 else '#e74c3c'}">{st['pnl_total']:+.2f}%</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Scoring AI — Trade Risk Report</title>
  <style>
    * {{ box-sizing: border-box; margin:0; padding:0; }}
    body {{ font-family: 'Segoe UI', sans-serif; background:#0d1117; color:#c9d1d9; padding:30px; }}
    h1 {{ font-size:1.8em; margin-bottom:6px; color:#58a6ff; }}
    .subtitle {{ color:#8b949e; font-size:0.9em; margin-bottom:30px; }}
    .cards {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:30px; }}
    .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:20px 28px; min-width:160px; }}
    .card .label {{ font-size:0.75em; color:#8b949e; text-transform:uppercase; letter-spacing:1px; }}
    .card .value {{ font-size:2em; font-weight:700; margin-top:4px; }}
    .green {{ color:#3fb950; }} .red {{ color:#f85149; }} .blue {{ color:#58a6ff; }} .yellow {{ color:#d29922; }}
    table {{ width:100%; border-collapse:collapse; background:#161b22; border-radius:8px; overflow:hidden; margin-bottom:30px; }}
    th {{ background:#21262d; color:#8b949e; font-size:0.75em; text-transform:uppercase; padding:10px 14px; text-align:left; }}
    td {{ padding:9px 14px; border-top:1px solid #21262d; font-size:0.85em; }}
    tr:hover td {{ background:#1c2128; }}
    h2 {{ font-size:1.1em; color:#58a6ff; margin-bottom:12px; }}
  </style>
</head>
<body>
  <h1>🤖 Scoring AI — Trade Risk Report</h1>
  <p class="subtitle">Generado: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | DB: {db.get('generated_at','')[:16]}</p>

  <div class="cards">
    <div class="card"><div class="label">Total Trades</div><div class="value blue">{db.get('total_trades',0)}</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value {'green' if db.get('win_rate',0) >= 50 else 'red'}">{db.get('win_rate',0):.1f}%</div></div>
    <div class="card"><div class="label">Ganadores</div><div class="value green">{db.get('winners',0)}</div></div>
    <div class="card"><div class="label">Perdedores</div><div class="value red">{db.get('losers',0)}</div></div>
    <div class="card"><div class="label">Símbolos</div><div class="value yellow">{len(symbol_stats)}</div></div>
  </div>

  <h2>📈 Rendimiento por Símbolo</h2>
  <table>
    <tr><th>Símbolo</th><th>Trades</th><th>Win Rate</th><th>PnL Total</th></tr>
    {sym_rows if sym_rows else '<tr><td colspan="4" style="text-align:center;color:#555">Sin datos</td></tr>'}
  </table>

  <h2>📋 Historial Completo de Trades</h2>
  <table>
    <tr><th>Fecha</th><th>Símbolo</th><th>Lado</th><th>Razón Cierre</th><th>PnL%</th><th>Resultado</th><th>Vector de Contexto</th></tr>
    {rows_html if rows_html else '<tr><td colspan="7" style="text-align:center;color:#555">Sin datos — ejecuta collector.py primero</td></tr>'}
  </table>

  <p style="color:#555;font-size:0.75em;text-align:center">
    Scoring AI v1.0 — Módulo independiente del bot  |  No modifica ningún archivo del bot activo
  </p>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[report] ✅  Report saved → {output_path}")
    if open_browser:
        webbrowser.open(f"file://{os.path.abspath(output_path)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    generate_report(args.output, args.open_browser)
