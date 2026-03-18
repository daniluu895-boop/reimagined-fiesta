from typing import Callable, Dict, Any, Awaitable, Union
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from database.database import async_session_maker
from database.models import User
from config import ADMIN_ID

class BanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], Dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: Dict[str, Any]
    ) -> Any:
        
        # event здесь — это гарантированно Message или CallbackQuery
        user_id = event.from_user.id
        
        if user_id == ADMIN_ID:
            return await handler(event, data)

        async with async_session_maker() as session:
            user = await session.scalar(select(User).where(User.telegram_id == user_id))
            if user and user.is_banned:
                if isinstance(event, Message):
                    await event.answer("🚫 Вы заблокированы.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Доступ заблокирован!", show_alert=True)
                return 

        return await handler(event, data)