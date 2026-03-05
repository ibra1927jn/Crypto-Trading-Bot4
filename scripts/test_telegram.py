"""Quick Telegram test."""
import aiohttp, asyncio

TOKEN = "8786260046:AAHWr2sZB3MpHS2Y_OTNX0cBa-JkVt-dEO4"
CHAT = "5822131920"

async def main():
    conn = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
        # Test 1: getMe
        print("[1] Testing getMe...")
        async with s.get(f"https://api.telegram.org/bot{TOKEN}/getMe") as r:
            print(f"    Status: {r.status}")
            data = await r.json()
            print(f"    Bot: {data.get('result', {}).get('username', 'unknown')}")

        # Test 2: sendMessage via GET (URL params)
        print("[2] Sending test message via GET...")
        msg = "🎯 CT4 — Test de conexión OK"
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT}&text={msg}"
        async with s.get(url) as r:
            print(f"    Status: {r.status}")
            body = await r.json()
            print(f"    OK: {body.get('ok')}")
            if not body.get('ok'):
                print(f"    Error: {body.get('description')}")

asyncio.run(main())
