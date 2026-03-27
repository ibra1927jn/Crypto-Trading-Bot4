import json

d = json.load(open('logs/live_check.json', encoding='utf-8'))
t = d['trader']

print('=== TRADE HISTORY ===')
for h in t['history']:
    sym = h['symbol']
    side = h['side']
    reason = h['reason']
    pnl = h['pnl']
    pnl_pct = h['pnl_pct']
    score = h['entry_score']
    print(f'  {sym:<15s} {side:<5s} {reason:<12s} PnL: ${pnl:+.4f} ({pnl_pct:+.1f}%) SC:{score}')

print()
print('=== OPEN POSITIONS ===')
for sym, p in t['positions'].items():
    side = p['side']
    entry = p['entry_price']
    sl = p['sl_price']
    tp = p['tp_price']
    hours = p['hours_held']
    score = p['entry_score']
    trail = p['trailing_active']
    amt = p['amount']
    print(f'  {sym:<15s} {side:<5s} entry:${entry:.6f} SL:${sl:.6f} TP:${tp:.6f} ${amt:.2f} {hours}h SC:{score} trail:{trail}')

print()
print('=== LAST 15 ALERTS ===')
for a in d['alerts'][:15]:
    t_str = a['time']
    sym = a['symbol']
    sigs = a['signals']
    print(f'  {t_str} {sym:<15s} {sigs}')

print()
print(f"Scans: {d.get('scan_count')}")
print(f"Mode: {d.get('market_mode')}")
print(f"F&G: {d.get('fear_greed')}")
