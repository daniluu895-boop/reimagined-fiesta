# main.py
import asyncio
import os
from aiogram import Dispatcher, Bot
from aiogram.client.session.aiohttp import AiohttpSession
from config import BOT_TOKEN
from utils.logger import logger
from database.database import init_db
from bot.handlers import router

PROXY_URL = os.getenv("PROXY_URL")

async def main():
    logger.info("Starting bot...")
    
    if not os.path.exists("logs"):
        os.makedirs("logs")

    await init_db()
    logger.info("Database initialized")
    
    from database.database import async_session_maker
    from database.models import Category
    from sqlalchemy import select
    
    async with async_session_maker() as session:
        if not await session.scalar(select(Category).limit(1)):
            session.add(Category(name="Футболки"))
            session.add(Category(name="Джинсы"))
            await session.commit()
            logger.info("Default categories added")

    # 🔹 Простая инициализация сессии
    if PROXY_URL:
        session = AiohttpSession(proxy=PROXY_URL)
        logger.info(f"Bot started with proxy: {PROXY_URL}")
    else:
        session = AiohttpSession()
        logger.warning("Bot started without proxy")
    
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")