from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
from utils.logger import logger

class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        
        # Пытаемся достать пользователя из события
        # Telegram-события или колбэки всегда имеют from_user
        user = getattr(event, 'from_user', None)
        
        # Если это Update, то ищем пользователя вложенно (в message, callback_query и т.д.)
        if not user and isinstance(event, Update):
            if event.message: user = event.message.from_user
            elif event.callback_query: user = event.callback_query.from_user
            elif event.edited_message: user = event.edited_message.from_user

        if user:
            # Определяем контент
            content = None
            if isinstance(event, Message) or (isinstance(event, Update) and event.message):
                msg = event.message if isinstance(event, Update) else event
                content = f"Msg: {msg.text or msg.caption or '[Media]'}"
            elif isinstance(event, CallbackQuery) or (isinstance(event, Update) and event.callback_query):
                cb = event.callback_query if isinstance(event, Update) else event
                content = f"Cb: {cb.data}"

            if content:
                logger.info(f"User {user.id} (@{user.username or 'NoUser'}): {content}")
        
        return await handler(event, data)