import asyncio
import os
from aiogram import Dispatcher, Bot
from aiogram.client.session.aiohttp import AiohttpSession
from config import BOT_TOKEN
from utils.logger import logger
from database.database import init_db
from bot.handlers import router, admin_router, warehouse_router, admin_users_router
# Импортируем миддлвары
from bot.middlewares.logging_middleware import LoggingMiddleware
from bot.middlewares.ban_middleware import BanMiddleware

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

    # Инициализация сессии
    if PROXY_URL:
        session = AiohttpSession(proxy=PROXY_URL)
        logger.info(f"Bot started with proxy: {PROXY_URL}")
    else:
        session = AiohttpSession()
        logger.warning("Bot started without proxy")
    
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher()

    # --- РЕГИСТРАЦИЯ МИДДЛВАРОВ ---
    # Порядок важен: сначала логгинг, потом проверка доступа
    dp.message.outer_middleware(LoggingMiddleware())
    dp.callback_query.outer_middleware(LoggingMiddleware())

    dp.message.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())


    # Подключаем роутеры
    dp.include_routers(router, admin_router, warehouse_router, admin_users_router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot is polling...")
    await dp.start_polling(bot)
    await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")