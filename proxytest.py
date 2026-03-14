# test_proxy.py
import os
from dotenv import load_dotenv
import asyncio
import aiohttp

load_dotenv()

PROXY = os.getenv("PROXY_URL")
print(f"🔍 Прокси из .env: {PROXY}")

async def test():
    try:
        async with aiohttp.ClientSession() as session:
            print(f"🔗 Подключаюсь через {PROXY}...")
            async with session.get("https://api.telegram.org", proxy=PROXY, timeout=10) as resp:
                print(f"✅ Успех! Статус: {resp.status}")
    except Exception as e:
        print(f"❌ Ошибка: {type(e).__name__}: {e}")

asyncio.run(test())