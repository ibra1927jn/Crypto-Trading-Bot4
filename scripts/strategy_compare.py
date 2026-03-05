"""
Strategy Comparison — Backtest on actual bot data
Compares 5 strategies using the evaluation log data.
"""
# Actual evaluations from Hetzner bot logs (29 hours of data)
# Format: (eval#, hour, marea, fuerza_adx, ballenas, rsi, price_approx)
evals = [
    # First session (laptop) - 10h
    (10,  "Feb28 04:10", False, 11.2, True,  50.0, 65700),
    (20,  "Feb28 05:10", False, 12.9, False, 50.0, 65600),
    (30,  "Feb28 08:00", False, 68.3, False, 11.9, 64200),
    (40,  "Feb28 08:50", False, 80.1, False, 44.5, 64100),
    (50,  "Feb28 09:40", False, 81.5, False, 37.4, 64050),
    (60,  "Feb28 10:30", False, 78.8, True,  52.8, 64000),
    (70,  "Feb28 11:25", False, 71.3, True,  51.3, 64050),
    (80,  "Feb28 12:15", False, 70.7, False, 58.2, 64100),
    (90,  "Feb28 13:10", False, 82.5, False, 45.7, 64000),
    (100, "Feb28 14:05", False, 84.5, True,  51.9, 64050),
    # Hetzner session - 29h
    (110, "Mar01 16:55", False, 82.3, True,  25.4, 66200),
    (120, "Mar01 17:45", False, 83.4, False, 36.7, 66100),
    (130, "Mar01 18:35", False, 67.8, False, 51.6, 66300),
    (140, "Mar01 19:25", False, 53.8, True,  36.2, 66200),
    (150, "Mar01 20:15", False, 51.0, False, 27.4, 66100),
    (160, "Mar01 21:05", False, 69.5, False, 31.8, 66150),
    (170, "Mar01 21:55", False, 72.3, False, 51.2, 66300),
    (180, "Mar01 22:45", False, 51.8, True,  38.0, 66250),
    (190, "Mar01 23:35", False, 42.6, False, 49.3, 66400),
    (200, "Mar02 00:25", False, 42.8, False, 53.3, 66500),
    (210, "Mar02 01:15", True,  43.5, True,  71.2, 66700),
    (220, "Mar02 02:05", True,  35.9, False, 55.9, 66600),
    (230, "Mar02 02:55", False, 29.0, False, 49.1, 66400),
    (240, "Mar02 03:45", True,  34.4, True,  67.2, 66650),
    (250, "Mar02 04:35", True,  43.5, False, 66.3, 66700),
    (260, "Mar02 05:25", True,  32.9, True,  51.0, 66600),
]

CURRENT_PRICE = 66534
RSI_OVERSOLD = 35

def simulate(name, buy_condition, sell_condition):
    """Simulate a strategy over the evaluation data."""
    trades = []
    holding = False
    entry_price = 0
    entry_time = ""
    
    for ev in evals:
        num, time, marea, adx, ballenas, rsi, price = ev
        
        if not holding and buy_condition(ev):
            holding = True
            entry_price = price
            entry_time = time
        elif holding and sell_condition(ev):
            pnl = price - entry_price
            pnl_pct = (pnl / entry_price) * 100
            trades.append((entry_time, time, entry_price, price, pnl, pnl_pct))
            holding = False
    
    # If still holding, calculate unrealized PnL
    if holding:
        pnl = CURRENT_PRICE - entry_price
        pnl_pct = (pnl / entry_price) * 100
        trades.append((entry_time, "ABIERTO", entry_price, CURRENT_PRICE, pnl, pnl_pct))
    
    total_pnl = sum(t[4] for t in trades)
    total_pct = sum(t[5] for t in trades)
    
    print(f"\n{'='*60}")
    print(f"📊 {name}")
    print(f"{'='*60}")
    print(f"  Trades: {len(trades)} | PnL total: ${total_pnl:.0f} | {total_pct:.2f}%")
    for t in trades:
        emoji = "🟢" if t[4] > 0 else "🔴"
        print(f"  {emoji} {t[0]} → {t[1]} | Entry: ${t[2]} → Exit: ${t[3]} | PnL: ${t[4]:.0f} ({t[5]:.2f}%)")
    if not trades:
        print("  ⚪ Sin trades")
    return len(trades), total_pnl, total_pct

print("=" * 60)
print("🔬 COMPARACIÓN DE ESTRATEGIAS — Datos reales 29h")
print(f"   Precio actual: ${CURRENT_PRICE}")
print("=" * 60)

# Strategy 1: Current (4 Laws - Sniper)
s1 = simulate(
    "ESTRATEGIA 1: Francotirador (actual)",
    lambda e: e[2] and e[3] > 20 and e[4] and e[5] < 35,  # All 4 laws
    lambda e: e[5] > 70  # RSI > 70
)

# Strategy 2: No Marea (3 Laws)
s2 = simulate(
    "ESTRATEGIA 2: Sin Marea (3 leyes)",
    lambda e: e[3] > 20 and e[4] and e[5] < 35,  # Skip Marea
    lambda e: e[5] > 65
)

# Strategy 3: RSI Extreme Only
s3 = simulate(
    "ESTRATEGIA 3: RSI Extremo (RSI < 25)",
    lambda e: e[5] < 25 and e[3] > 40,  # RSI extreme + ADX
    lambda e: e[5] > 55
)

# Strategy 4: Simple RSI
s4 = simulate(
    "ESTRATEGIA 4: RSI Simple (comprar < 35, vender > 60)",
    lambda e: e[5] < 35,
    lambda e: e[5] > 60
)

# Strategy 5: Marea + Pullback (2 leyes relajadas)
s5 = simulate(
    "ESTRATEGIA 5: Solo Marea + Pullback (sin Fuerza ni Ballenas)",
    lambda e: e[2] and e[5] < 45,  # Marea OK + RSI moderado
    lambda e: e[5] > 65
)

print(f"\n{'='*60}")
print("📋 RESUMEN COMPARATIVO")
print(f"{'='*60}")
print(f"{'Estrategia':<45} {'Trades':>6} {'PnL':>10} {'%':>8}")
print("-" * 72)
results = [
    ("1. Francotirador (actual)", s1),
    ("2. Sin Marea (3 leyes)", s2),
    ("3. RSI Extremo (<25)", s3),
    ("4. RSI Simple (<35/>60)", s4),
    ("5. Marea + Pullback relajado", s5),
]
for name, (trades, pnl, pct) in results:
    emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
    print(f"  {emoji} {name:<43} {trades:>4} {pnl:>+10.0f}$ {pct:>+7.2f}%")
