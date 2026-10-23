from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery
import logging

class LoadingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery) or not event.message:
            return await handler(event, data)
        waiting = None
        try:
            await event.answer()
            waiting = await event.message.answer("⏳ Секунду, готовлю…")
            return await handler(event, data)
        finally:
            if waiting:
                try:
                    await waiting.delete()
                except Exception:
                    logging.debug("Loading message already removed")
