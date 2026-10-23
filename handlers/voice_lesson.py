
import os
from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile

from services.student_service import get_student, get_student_state
from services.access_service import has_access
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from services.voice_lesson_service import create_voice_lesson
from services.user_session import set_session

router=Router()

@router.callback_query(F.data=="voice_lesson")
async def voice_lesson(callback:CallbackQuery):
    await callback.answer()
    msg=await callback.message.answer("🎧 Creating your AI voice lesson...")
    try:
        student=get_student(callback.from_user.id)
        if not student:
            await msg.edit_text("Please use /start first.")
            return

        state=get_student_state(student["id"]) or {}
        if not has_access(student, state.get("current_block"), state.get("current_topic")):
            await msg.edit_text(
                "🔒 Бесплатно доступен только первый урок (1.1).\n\n"
                "Чтобы продолжить обучение, необходима подписка 19,90 USD в месяц "
                "с автоматическим ежемесячным продлением.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Подписаться · 19,90 USD/месяц", callback_data="subscription")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
                ]),
            )
            return

        result=await create_voice_lesson(student["id"], callback.from_user.id)
        if not result:
            await msg.edit_text("Lesson not found.")
            return

        audio_path, lesson=result
        await msg.delete()
        await callback.message.answer_voice(
            FSInputFile(audio_path),
            caption=f"🎧 {lesson.get('topic')}"
        )
        os.remove(audio_path)

    except Exception as e:
        print("VOICE LESSON ERROR",e)
        await msg.edit_text("Unable to create voice lesson.")

@router.callback_query(F.data=="speaking_practice")
async def speaking_practice(callback:CallbackQuery):
    await callback.answer()
    set_session(callback.from_user.id, "speaking")
    await callback.message.answer(
        "🎤 Speaking Practice\n\n"
        "Send your Greek voice message now. I will analyze it for your "
        "current block/topic and reply with an AI voice explanation."
    )
