import asyncio
from aiogram import Dispatcher, Bot
from config import BOT_TOKEN
from utils.logger import logger
from database.database import init_db
from bot.handlers import router

async def main():
    logger.info("Starting bot...")
    
    # Создаем папку логов, если нет
    import os
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Инициализация БД
    await init_db()
    logger.info("Database initialized")
    
    # Добавим тестовую категорию, если их нет
    from database.database import async_session_maker
    from database.models import Category
    from sqlalchemy import select
    async with async_session_maker() as session:
        if not await session.scalar(select(Category).limit(1)):
            session.add(Category(name="Футболки"))
            session.add(Category(name="Джинсы"))
            await session.commit()
            logger.info("Default categories added")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")