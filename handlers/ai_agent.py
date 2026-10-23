from aiogram import Router, F
from aiogram.types import Message

from services.ai_agent import process_user_request

router = Router()


@router.message(F.text.startswith("/ai"))
async def ai_agent_command(message: Message):
    if not message.from_user:
        return

    question = message.text.replace("/ai", "", 1).strip()
    if not question:
        await message.answer("🤖 Please write your question after /ai")
        return

    thinking = await message.answer("🤔 AI is checking...")
    try:
        response = await process_user_request(
            telegram_user_id=message.from_user.id,
            user_message=question,
        )
        try:
            await thinking.delete()
        except Exception:
            pass
        await message.answer(response)
    except Exception as error:
        print("AI COMMAND ERROR:", repr(error))
        try:
            await thinking.delete()
        except Exception:
            pass
        await message.answer("The AI tutor is temporarily unavailable. Please try again.")
