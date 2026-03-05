"""Clean up orphaned BTC from Binance Testnet."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ccxt.async_support as ccxt
import aiosqlite
from config.settings import API_KEY, API_SECRET, EXCHANGE_SANDBOX, DB_PATH

async def clean():
    ex = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'sandbox': EXCHANGE_SANDBOX,
    })
    await ex.load_markets()
    
    # 1. Cancel ALL open orders
    orders = await ex.fetch_open_orders('BTC/USDT')
    print(f"Open orders: {len(orders)}")
    for o in orders:
        await ex.cancel_order(o['id'], 'BTC/USDT')
        print(f"  Cancelled: {o['id']}")
    
    # 2. Check BTC balance
    bal = await ex.fetch_balance()
    btc = bal.get('BTC', {}).get('total', 0)
    usdt = bal.get('USDT', {}).get('total', 0)
    print(f"BTC balance: {btc}")
    print(f"USDT balance: ${usdt:.2f}")
    
    # 3. Sell ALL BTC
    if btc > 0.00001:
        ticker = await ex.fetch_ticker('BTC/USDT')
        print(f"BTC price: ${ticker['last']:.2f}")
        amount = float(ex.amount_to_precision('BTC/USDT', btc))
        print(f"Selling {amount} BTC...")
        order = await ex.create_order('BTC/USDT', 'market', 'sell', amount)
        price = order.get('average') or order.get('price') or '??'
        print(f"SOLD: {order['id']} @ ${price}")
    else:
        print("No BTC to sell.")
    
    # 4. Final exchange balance
    await asyncio.sleep(1)
    bal2 = await ex.fetch_balance()
    btc2 = bal2.get('BTC', {}).get('total', 0)
    usdt2 = bal2.get('USDT', {}).get('total', 0)
    print(f"\n=== EXCHANGE CLEAN ===")
    print(f"BTC:  {btc2}")
    print(f"USDT: ${usdt2:.2f}")
    await ex.close()
    
    # 5. Clean SQLite
    print(f"\n=== CLEANING DATABASE: {DB_PATH} ===")
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ct4.db')
    # Try both paths
    for path in [DB_PATH, db_path]:
        if os.path.exists(path):
            print(f"Found DB: {path}")
            async with aiosqlite.connect(path) as db:
                cursor = await db.execute("SELECT COUNT(*) FROM positions WHERE status IN ('OPEN', 'ORPHANED')")
                count = (await cursor.fetchone())[0]
                print(f"Open/Orphaned positions: {count}")
                await db.execute(
                    "UPDATE positions SET status = 'CLOSED', pnl = 0, closed_at = datetime('now') "
                    "WHERE status IN ('OPEN', 'ORPHANED')"
                )
                await db.commit()
                print(f"Closed {count} positions.")
                cursor2 = await db.execute("SELECT COUNT(*) FROM positions WHERE status IN ('OPEN', 'ORPHANED')")
                remaining = (await cursor2.fetchone())[0]
                print(f"Remaining open: {remaining}")
            break
    else:
        print("WARNING: No database found!")
    
    print("\n✅ LIMPIEZA COMPLETA")

asyncio.run(clean())
