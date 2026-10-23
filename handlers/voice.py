from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, FSInputFile

from services.speech_service import analyze_greek_speech, transcribe_greek_voice
from services.student_service import get_student, get_student_state
from services.access_service import has_access
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from services.voice_service import generate_voice
from services.voice_practice_service import save_voice_practice
from services.user_session import get_session, set_session
from services.ai_agent import process_conversation

router = Router()


async def _send_voice(bot, chat_id: int, text: str):
    audio_path = await generate_voice(text)
    try:
        await bot.send_voice(chat_id=chat_id, voice=FSInputFile(audio_path))
    finally:
        Path(audio_path).unlink(missing_ok=True)


@router.message(F.voice)
async def voice_message_handler(message: Message):
    if not message.voice or not message.from_user:
        return

    user_id = message.from_user.id
    session = get_session(user_id)
    mode = session.get("mode")

    # Natural AI mentor voice conversation. Voice input receives a voice reply,
    # while text input can remain text unless the AI decides voice is useful.
    if mode == "tutor_chat":
        try:
            student = get_student(user_id)
            state = get_student_state(student["id"]) if student else None
            if not student or not state:
                await message.answer("Пожалуйста, сначала отправьте /start.")
                return
            if not has_access(student, state.get("current_block"), state.get("current_topic")):
                await message.answer(
                    "🔒 Бесплатно доступен только первый урок (1.1).\n\n"
                    "Чтобы продолжить обучение, необходима подписка 19,90 USD в месяц "
                    "с автоматическим ежемесячным продлением. Освобождение или отмена оплаты "
                    "для платных уроков не предусмотрены.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Подписаться · 19,90 USD/месяц", callback_data="subscription")],
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
                    ]),
                )
                return
            transcription = await transcribe_greek_voice(
                message.bot,
                message.voice,
                language=None,
            )
            print(f"TUTOR VOICE TRANSCRIPTION [{user_id}]: {transcription}")
            student = get_student(user_id)
            context = ""
            if student:
                state = get_student_state(student["id"]) or {}
                context = (
                    f"Level: {state.get('level') or 'A1'}\n"
                    f"Block: {state.get('current_block') or ''}\n"
                    f"Topic: {state.get('current_topic') or ''}"
                )
            result = await process_conversation(
                telegram_user_id=user_id,
                user_message=transcription,
                context=context + "\nThe student sent this as a voice message. Prefer a natural voice reply.",
            )
            if result.get("action") == "assessment":
                from handlers.assessment import begin_assessment
                await begin_assessment(message, announce=True)
                return
            if (result.get("action_result") or {}).get("result") == "payment_required":
                await message.answer(
                    result["reply"],
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Подписаться · 19,90 USD/месяц", callback_data="subscription")],
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
                    ]),
                )
                return
            await _send_voice(message.bot, message.chat.id, result["reply"])
            return
        except Exception as error:
            print("AI TUTOR VOICE ERROR:", repr(error))
            await message.answer("I could not create the AI voice response. Please try again.")
            return

    # Existing pronunciation/speaking practice remains untouched.
    if mode != "speaking":
        await message.answer("Please open Continue Learning first.")
        return

    try:
        student = get_student(user_id)
        if not student:
            await message.answer("Please use /start first.")
            return

        state = get_student_state(student["id"]) or {}
        context = (
            f"Level: {state.get('level') or 'A1'}\n"
            f"Block: {state.get('current_block') or ''}\n"
            f"Topic: {state.get('current_topic') or ''}"
        )

        result = await analyze_greek_speech(
            bot=message.bot,
            voice=message.voice,
            block_context=context,
        )

        try:
            save_voice_practice(
                student_id=student["id"],
                block=str(state.get("current_block") or ""),
                topic=str(state.get("current_topic") or ""),
                transcription=result["transcription"],
                feedback=result["analysis"],
            )
        except Exception as save_error:
            print("VOICE PRACTICE SAVE ERROR:", repr(save_error))

        await _send_voice(message.bot, message.chat.id, result["analysis"])

    except Exception as error:
        print("SPEAKING PRACTICE ERROR:", repr(error))
        await message.answer("Sorry, I could not analyze your speaking practice right now.")
