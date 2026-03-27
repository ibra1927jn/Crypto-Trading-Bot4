"""
🔬 AUTOPSIA V11 — Radiografía de las últimas 24h
Ejecutar: python scripts/autopsia_v11.py
"""
import pandas as pd, json, os, sys
from pathlib import Path

BASE = Path(__file__).parent.parent

def analizar(csv_path=None, state_path=None):
    csv_path   = csv_path   or BASE / 'logs' / 'trades.csv'
    state_path = state_path or BASE / 'state' / 'trader_state.json'

    print("=" * 55)
    print("  AUTOPSIA V11 — RISK MANAGEMENT")
    print("=" * 55)

    # Load live state
    if os.path.exists(state_path):
        with open(state_path) as f:
            st = json.load(f)
        bal = st.get('balance', 0)
        pnl = st.get('total_pnl', 0)
        trades = st.get('total_trades', 0)
        wins   = st.get('total_wins', 0)
        wr     = wins/trades*100 if trades > 0 else 0
        print(f"  Balance actual : ${bal:.4f}")
        print(f"  PnL total      : ${pnl:+.4f}")
        print(f"  Trades         : {trades} | WR: {wr:.1f}%")
        print(f"  Open pos       : {len(st.get('positions', {}))}")
        bans = st.get('sl_ban_until', {})
        if bans:
            print(f"\n  SL-BANS activos: {len(bans)}")
            for sym, until in bans.items():
                import time
                rem = (float(until) - time.time()) / 3600
                print(f"    {sym}: {rem:.1f}h restantes")
        print()

    if not os.path.exists(csv_path):
        print("  Sin trades en CSV todavía."); return

    df = pd.read_csv(csv_path)
    if df.empty: print("  CSV vacío."); return

    pnl_col  = next((c for c in df.columns if 'pnl' in c.lower() and 'pct' not in c.lower()), None)
    side_col = next((c for c in df.columns if 'side' in c.lower()), None)
    reas_col = next((c for c in df.columns if 'reason' in c.lower()), None)
    if not pnl_col: print("Columna PnL no encontrada"); return

    wins_df   = df[df[pnl_col] > 0]
    losses_df = df[df[pnl_col] <= 0]
    gp = wins_df[pnl_col].sum()
    gl = abs(losses_df[pnl_col].sum())
    pf = gp/gl if gl > 0 else float('inf')
    net = gp - gl

    print(f"  Trades CSV     : {len(df)}")
    print(f"  Win Rate       : {len(wins_df)/len(df)*100:.1f}%")
    print(f"  Net PnL        : ${net:+.4f}")
    print(f"  Profit Factor  : {pf:.2f}")
    print(f"  Avg Win        : ${wins_df[pnl_col].mean():+.4f}" if not wins_df.empty else "  Avg Win  : n/a")
    print(f"  Avg Loss       : ${losses_df[pnl_col].mean():+.4f}" if not losses_df.empty else "  Avg Loss : n/a")

    # Direction breakdown
    if side_col:
        print()
        for side in ['long', 'short']:
            sub = df[df[side_col].str.lower() == side]
            if len(sub) == 0: continue
            sw  = len(sub[sub[pnl_col] > 0])
            swr = sw/len(sub)*100
            spnl = sub[pnl_col].sum()
            print(f"  {side.upper():<6} → {len(sub):>3} trades | WR:{swr:.0f}% | PnL:${spnl:+.4f}")

    # Exit reason breakdown
    if reas_col:
        print()
        print(f"  {'Reason':<10} {'N':>4} {'WR':>6} {'PnL':>10}")
        for r, g in df.groupby(reas_col):
            w  = len(g[g[pnl_col] > 0])
            rw = w/len(g)*100
            rp = g[pnl_col].sum()
            print(f"  {str(r):<10} {len(g):>4} {rw:>5.0f}% ${rp:>+8.4f}")

    # SL ban bullets dodged
    import subprocess
    try:
        result = subprocess.run(
            ['grep', '-c', 'SL-banned', str(BASE / 'logs' / 'monitor.log')],
            capture_output=True, text=True)
        bans_count = int(result.stdout.strip())
        print(f"\n  BALAS ESQUIVADAS: {bans_count} entradas bloqueadas por SL-ban")
    except: pass

    print("=" * 55)

if __name__ == '__main__':
    analizar()
