from pathlib import Path
from aiogram.types import FSInputFile
from services.curriculum_service import split_message
from services.voice_service import generate_voice

async def send_audio_reply(bot, chat_id: int, text: str, reply_markup=None):
    chunks = split_message(text, max_length=3500)
    for index, chunk in enumerate(chunks):
        path = await generate_voice(chunk)
        try:
            await bot.send_voice(chat_id=chat_id, voice=FSInputFile(path),
                                 reply_markup=reply_markup if index == len(chunks)-1 else None)
        finally:
            Path(path).unlink(missing_ok=True)
