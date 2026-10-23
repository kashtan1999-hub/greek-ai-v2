import os
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message, FSInputFile

from services.ai_agent import process_conversation
from services.conversation_log import log_turn
from services.student_service import get_student, get_student_state
from services.access_service import has_access
from services.curriculum_service import split_message
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from services.user_session import set_session, get_session, clear_session
from services.voice_service import generate_voice

router = Router()


def stop_tutor_mode(user_id: int) -> None:
    session = get_session(user_id)
    if session.get("mode") in {"tutor_chat", "tutor_test", "assessment_questionnaire", "assessment_test"}:
        clear_session(user_id)


def start_tutor_mode(user_id: int, topic: str | None = None, russian_help: bool = False) -> None:
    # Topic/russian_help are retained for compatibility with the existing learning flow.
    set_session(user_id, "tutor_chat", topic=(topic or "").strip(), russian_help=russian_help)


def _current_context(user_id: int) -> str:
    student = get_student(user_id)
    if not student:
        return ""
    state = get_student_state(student["id"]) or {}
    return (
        f"Level: {state.get('level') or 'A1'}\n"
        f"Block: {state.get('current_block') or ''}\n"
        f"Topic: {state.get('current_topic') or ''}"
    )


async def _send_voice(bot, chat_id: int, text: str):
    audio_path = await generate_voice(text)
    try:
        await bot.send_voice(chat_id=chat_id, voice=FSInputFile(audio_path))
    finally:
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception:
            pass


@router.message(F.text, lambda message: bool(message.from_user) and get_session(message.from_user.id).get("mode") == "tutor_chat")
async def tutor_question(message: Message):
    user_id = message.from_user.id
    question = (message.text or "").strip()
    if not question:
        return

    try:
        student = get_student(user_id)
        state = get_student_state(student["id"]) if student else None
        if not student or not state:
            await message.answer("Пожалуйста, сначала отправьте /start.")
            return
        if not has_access(student, state.get("current_block"), state.get("current_topic")):
            await message.answer(
                "🔒 Бесплатно доступен только первый урок (1.1).\n\n"
                "Чтобы продолжить обучение, необходима подписка **19,90 USD в месяц** "
                "с автоматическим ежемесячным продлением. Освобождение или отмена оплаты "
                "для платных уроков не предусмотрены.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Подписаться · 19,90 USD/месяц", callback_data="subscription")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
                ]),
                parse_mode="Markdown",
            )
            return

        result = await process_conversation(
            telegram_user_id=user_id,
            user_message=question,
            context=_current_context(user_id),
        )
        action_result = result.get("action_result") or {}
        if action_result.get("result") == "payment_required":
            await message.answer(
                result["reply"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Подписаться · 19,90 USD/месяц", callback_data="subscription")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
                ]),
            )
            return

        # The AI may decide that an assessment is appropriate. Import locally to
        # avoid circular imports between tutor and assessment handlers.
        if result.get("action") == "assessment":
            from handlers.assessment import begin_assessment
            await begin_assessment(message, announce=True)
            return

        if result.get("response_mode") == "voice":
            await _send_voice(message.bot, message.chat.id, result["reply"])
        else:
            await message.answer(result["reply"])
    except Exception as error:
        print("TUTOR CONVERSATION ERROR:", repr(error))
        await message.answer("I could not answer right now. Please try again.")


# Kept as a compatibility entry point for existing imports. The old
# button-driven AI Tutor entry points are intentionally no longer used.
@router.callback_query(F.data == "ai_tutor_help")
async def ai_tutor_help(callback):
    start_tutor_mode(callback.from_user.id)
    await callback.message.answer("🤖 You can now talk to me naturally in the chat. Ask me anything about your Greek learning.")
    await callback.answer()


@router.callback_query(F.data == "ask_tutor")
async def ask_tutor_button(callback):
    start_tutor_mode(callback.from_user.id)
    await callback.message.answer("🤖 You can now talk to me naturally in the chat.")
    await callback.answer()
