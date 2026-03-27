"""
🔍 CHECK: ¿Cuáles de nuestras monedas están en Binance Testnet?
================================================================
Binance testnet tiene pares limitados. Verificamos disponibilidad.
También comprobamos pares en Binance Spot real para monitoreo.
"""
import sys, ccxt, time

def p(msg): print(msg); sys.stdout.flush()

def main():
    p("="*80)
    p("🔍 VERIFICACIÓN: Testnet vs Mainnet para monedas baratas")
    p("="*80)
    
    # Nuestras top 20 monedas del scanner
    target_coins = [
        'CHESS', 'COS', 'DEGO', 'BABY', 'RESOLV', 'BANANAS31',
        'MBOX', 'FXS', 'VOXEL', 'HUMA', 'SIGN', 'PLUME',
        'XRP', 'DOGE', 'ADA', 'SHIB', 'TRX', 'AVAX',
        'ALGO', 'VET', 'CRV', 'ANKR', 'EDEN', 'JASMY',
        'GALA', 'CHZ', 'FLOKI', 'PEPE', 'BONK', 'WIF'
    ]
    
    # 1. Check Binance Testnet
    p("\n📡 Conectando a Binance TESTNET...")
    try:
        testnet = ccxt.binance({
            'timeout': 15000,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        testnet.set_sandbox_mode(True)
        testnet_markets = testnet.load_markets()
        testnet_symbols = set(testnet_markets.keys())
        p(f"   ✅ Testnet: {len(testnet_symbols)} pares disponibles")
        
        # Mostrar TODOS los pares testnet USDT
        testnet_usdt = sorted([s for s in testnet_symbols if '/USDT' in s])
        p(f"\n   Pares USDT en testnet ({len(testnet_usdt)}):")
        for s in testnet_usdt:
            m = testnet_markets[s]
            p(f"   • {s}")
    except Exception as e:
        p(f"   ⚠️ Error testnet: {e}")
        testnet_symbols = set()
        testnet_usdt = []
    
    # 2. Check Binance MAINNET (solo lectura - no necesita API key)
    p("\n📡 Conectando a Binance MAINNET...")
    mainnet = ccxt.binance({'timeout': 15000, 'enableRateLimit': True})
    mainnet_markets = mainnet.load_markets()
    
    # 3. Comparar
    p(f"\n{'='*80}")
    p(f"📊 DISPONIBILIDAD DE MONEDAS")
    p(f"{'='*80}")
    p(f"{'Moneda':<15s} | {'Mainnet':^10s} | {'Testnet':^10s} | {'Precio':>10s} | {'Estado':^10s}")
    p(f"{'-'*15}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")
    
    available_testnet = []
    available_mainnet_only = []
    
    for coin in target_coins:
        sym = f"{coin}/USDT"
        in_main = sym in mainnet_markets
        in_test = sym in testnet_symbols
        
        price_str = ""
        if in_main:
            try:
                t = mainnet.fetch_ticker(sym)
                price_str = f"${t['last']:.4f}" if t.get('last') and t['last'] < 10 else f"${t['last']:.2f}" if t.get('last') else "?"
                time.sleep(0.1)
            except:
                price_str = "?"
        
        main_sym = '✅' if in_main else '❌'
        test_sym = '✅' if in_test else '❌'
        
        if in_test:
            estado = '🟢 FULL'
            available_testnet.append(sym)
        elif in_main:
            estado = '🟡 LIVE'
            available_mainnet_only.append(sym)
        else:
            estado = '🔴 N/A'
        
        p(f"{sym:<15s} | {main_sym:^10s} | {test_sym:^10s} | {price_str:>10s} | {estado:^10s}")
    
    # 4. Resumen
    p(f"\n{'='*80}")
    p(f"📋 RESUMEN")
    p(f"{'='*80}")
    p(f"   Testnet disponibles ({len(available_testnet)}):")
    for s in available_testnet:
        p(f"   ✅ {s}")
    
    p(f"\n   Solo Mainnet ({len(available_mainnet_only)}):")
    for s in available_mainnet_only:
        p(f"   🟡 {s} (monitoreo real, paper trading simulado)")
    
    p(f"\n{'='*80}")
    p(f"💡 PLAN:")
    p(f"   • Monitorear TODAS en mainnet (lee precios, sin comprar)")
    p(f"   • Paper trading: simulación interna (no necesita testnet)")
    p(f"   • Cuando esté validado → operar con dinero real en mainnet")
    p(f"{'='*80}")

if __name__ == '__main__':
    main()
