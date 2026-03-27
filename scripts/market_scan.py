"""Quick market scanner — find hot coins right now."""
import ccxt

ex = ccxt.binance({'timeout': 30000})
tickers = ex.fetch_tickers()
results = []
for sym, t in tickers.items():
    if not sym.endswith('/USDT'): continue
    if ':' in sym: continue
    price = t.get('last', 0) or 0
    if price <= 0 or price > 3: continue
    vol = t.get('quoteVolume', 0) or 0
    if vol < 500000: continue
    chg = t.get('percentage', 0) or 0
    high = t.get('high', 0) or 0
    low = t.get('low', 0) or 0
    rng = (high - low) / low * 100 if low > 0 else 0
    results.append((sym, price, chg, vol, rng, high, low))

print("=" * 70)
print("TOP GAINERS (<$3, Vol>$500k) — AHORA MISMO")
print("=" * 70)
results.sort(key=lambda x: -x[2])
print(f"{'Coin':<18s} {'Price':>12s} {'24h%':>8s} {'Volume$':>14s} {'Range%':>8s}")
print("-" * 65)
for r in results[:30]:
    icon = '\U0001F680' if r[2] > 10 else ('\U0001F7E2' if r[2] > 3 else ('\U0001F7E1' if r[2] > 0 else '\U0001F534'))
    print(f"{icon} {r[0]:<15s} ${r[1]:<11.6f} {r[2]:>+7.1f}% ${r[3]:>13,.0f} {r[4]:>7.1f}%")

print()
print("=" * 70)
print("TOP VOLUME (<$3) — Las mas liquidas")
print("=" * 70)
results.sort(key=lambda x: -x[3])
for r in results[:15]:
    icon = '\U0001F680' if r[2] > 10 else ('\U0001F7E2' if r[2] > 3 else ('\U0001F7E1' if r[2] > 0 else '\U0001F534'))
    print(f"{icon} {r[0]:<15s} ${r[1]:<11.6f} {r[2]:>+7.1f}% ${r[3]:>13,.0f} {r[4]:>7.1f}%")

print()
print("=" * 70)
print("BEST RANGE (<$3) — Mayor rango diario (oportunidad)")
print("=" * 70)
results.sort(key=lambda x: -x[4])
for r in results[:15]:
    icon = '\U0001F680' if r[2] > 10 else ('\U0001F7E2' if r[2] > 3 else ('\U0001F7E1' if r[2] > 0 else '\U0001F534'))
    print(f"{icon} {r[0]:<15s} ${r[1]:<11.6f} {r[2]:>+7.1f}% ${r[3]:>13,.0f} {r[4]:>7.1f}%")

# Check which are NOT in our current watchlist
current = ['CHESS','COS','DEGO','BABY','RESOLV','BANANAS31','MBOX','HUMA','SIGN','PLUME',
           'DOGE','XRP','ADA','JASMY','GALA','CHZ','FLOKI','PEPE','BONK','WIF']
print()
print("=" * 70)
print("NEW OPPORTUNITIES (not in watchlist)")
print("=" * 70)
results.sort(key=lambda x: -x[2])
for r in results:
    base = r[0].replace('/USDT','')
    if base not in current and r[2] > 2 and r[3] > 1000000:
        print(f"  {r[0]:<15s} ${r[1]:<11.6f} {r[2]:>+7.1f}% Vol:${r[3]:>13,.0f} Rng:{r[4]:>5.1f}%")
