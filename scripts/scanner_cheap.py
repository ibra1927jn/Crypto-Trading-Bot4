"""
🔍 SCANNER: Monedas baratas (< $3) con movimiento diario alto
===============================================================
Objetivo: Encontrar ~20 monedas donde con $30 puedas hacer $0.10+
Lógica: Si una moneda de $0.50 se mueve $0.05 → con 60 unidades = $3
"""
import sys, ccxt, time

def p(msg): print(msg); sys.stdout.flush()

def main():
    p("="*90)
    p("🔍 SCANNER: Monedas < $3 en Binance con más movimiento diario")
    p("   Capital: $30 | Objetivo: $0.10+ por trade")
    p("="*90)
    
    ex = ccxt.binance({'timeout': 30000, 'enableRateLimit': True})
    
    # 1. Obtener todos los pares USDT
    p("\n📥 Cargando mercados...")
    markets = ex.load_markets()
    usdt_pairs = [s for s, m in markets.items() 
                  if s.endswith('/USDT') 
                  and m.get('active', True)
                  and m.get('spot', True)
                  and not s.startswith('USDC')
                  and not s.startswith('BUSD')
                  and not s.startswith('TUSD')
                  and not s.startswith('DAI')]
    p(f"   ✅ {len(usdt_pairs)} pares USDT encontrados")
    
    # 2. Obtener tickers (precio actual + volumen 24h)
    p("\n📊 Obteniendo precios y volúmenes...")
    tickers = ex.fetch_tickers()
    
    # 3. Filtrar: < $3, volumen > $1M/día
    cheap = []
    for symbol, t in tickers.items():
        if not symbol.endswith('/USDT'): continue
        price = t.get('last', 0) or 0
        vol_24h = t.get('quoteVolume', 0) or 0  # Volumen en USDT
        high_24h = t.get('high', 0) or 0
        low_24h = t.get('low', 0) or 0
        pct_change = t.get('percentage', 0) or 0
        
        if price <= 0 or price > 3.0: continue
        if vol_24h < 1_000_000: continue  # Min $1M volumen diario
        
        # Rango diario en % y en $
        if low_24h > 0:
            daily_range_pct = (high_24h - low_24h) / low_24h * 100
            daily_range_usd = high_24h - low_24h
        else:
            daily_range_pct = 0
            daily_range_usd = 0
        
        # Con $30, ¿cuántas unidades compro y cuánto gano si captura 50% del rango?
        units = 30 / price
        potential_gain = units * (daily_range_usd * 0.5)  # 50% del rango capturado
        
        cheap.append({
            'symbol': symbol,
            'price': price,
            'vol_24h': vol_24h,
            'range_pct': daily_range_pct,
            'range_usd': daily_range_usd,
            'pct_change': pct_change,
            'units_30': units,
            'potential': potential_gain,
        })
    
    # Ordenar por potencial de ganancia
    cheap.sort(key=lambda x: -x['potential'])
    
    p(f"\n   ✅ {len(cheap)} monedas < $3 con volumen > $1M/día")
    
    # 4. Mostrar Top 30
    p(f"\n{'='*90}")
    p(f"🏆 TOP 30 MONEDAS BARATAS CON MÁS MOVIMIENTO")
    p(f"{'='*90}")
    p(f"{'#':>2s} {'Moneda':<12s} | {'Precio':>8s} | {'Vol 24h':>10s} | {'Rango%':>7s} | "
      f"{'Rango$':>8s} | {'Unid/$30':>8s} | {'Ganancia*':>10s} | {'24h%':>6s}")
    p(f"{'-'*2} {'-'*12}-+-{'-'*8}-+-{'-'*10}-+-{'-'*7}-+-"
      f"{'-'*8}-+-{'-'*8}-+-{'-'*10}-+-{'-'*6}")
    
    for i, c in enumerate(cheap[:30], 1):
        vol_str = f"${c['vol_24h']/1e6:.1f}M"
        e = '🟢' if c['potential'] >= 1.0 else ('🟡' if c['potential'] >= 0.5 else '⚪')
        p(f"{i:2d} {c['symbol']:<12s} | ${c['price']:>7.4f} | {vol_str:>10s} | "
          f"{c['range_pct']:>6.1f}% | ${c['range_usd']:>7.5f} | "
          f"{c['units_30']:>8.0f} | {e} ${c['potential']:>8.2f} | {c['pct_change']:>+5.1f}%")
    
    p(f"\n   * Ganancia = $30 × (50% del rango diario)")
    p(f"   * No incluye comisiones (0.1% por trade = ~$0.06)")
    
    # 5. Las mejores 20 para operar
    p(f"\n{'='*90}")
    p(f"📋 LAS 20 MEJORES PARA OPERAR (> $0.50 ganancia potencial)")
    p(f"{'='*90}")
    
    top20 = [c for c in cheap if c['potential'] >= 0.50][:20]
    
    symbols_list = []
    for i, c in enumerate(top20, 1):
        e = '🟢' if c['potential'] >= 1.0 else '🟡'
        p(f"   {i:2d}. {c['symbol']:<12s} — ${c['price']:.4f} | "
          f"Rango: {c['range_pct']:.1f}% (${c['range_usd']:.5f}) | "
          f"Vol: ${c['vol_24h']/1e6:.1f}M | {e} Potencial: ${c['potential']:.2f}/trade")
        symbols_list.append(c['symbol'].replace('/USDT', ''))
    
    p(f"\n   SYMBOLS para .env: {','.join(s + '/USDT' for s in symbols_list)}")
    
    # 6. Detalle: para cada top 5, cuánto necesitas que suba para ganar $1
    p(f"\n{'='*90}")
    p(f"💰 ¿CUÁNTO NECESITA SUBIR CADA UNA PARA GANAR $1?")
    p(f"{'='*90}")
    
    for c in top20[:10]:
        units = 30 / c['price']
        move_for_1 = 1.0 / units  # $ que necesita subir por unidad
        pct_for_1 = move_for_1 / c['price'] * 100
        moves_per_day = c['range_usd'] / move_for_1 if move_for_1 > 0 else 0
        
        p(f"   {c['symbol']:<12s}: Necesita subir ${move_for_1:.6f} ({pct_for_1:.2f}%) → "
          f"Rango diario = {moves_per_day:.1f}× ese movimiento")
    
    p(f"\n{'='*90}")

if __name__ == '__main__':
    main()
