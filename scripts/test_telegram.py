"""Quick Telegram test."""
import aiohttp, asyncio, os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

async def main():
    if not TOKEN or not CHAT:
        print("ERROR: Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env")
        return

    conn = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as s:
        # Test 1: getMe
        print("[1] Testing getMe...")
        async with s.get(f"https://api.telegram.org/bot{TOKEN}/getMe") as r:
            print(f"    Status: {r.status}")
            data = await r.json()
            print(f"    Response: {data}")

        # Test 2: sendMessage
        print("[2] Testing sendMessage...")
        msg = "CT4 Telegram test - connection OK"
        async with s.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT, "text": msg}
        ) as r:
            print(f"    Status: {r.status}")
            data = await r.json()
            print(f"    Response: {data}")

asyncio.run(main())
