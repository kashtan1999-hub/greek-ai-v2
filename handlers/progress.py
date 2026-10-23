from aiogram import Router
from aiogram.types import CallbackQuery

from services.progress_service import (
    get_student_progress,
    format_progress_message,
)
from services.student_service import get_student
from services.ui_manager import replace_callback_ui
from keyboards.learning import back_to_menu


router = Router()


@router.callback_query(lambda call: call.data == "my_progress")
async def my_progress(callback: CallbackQuery):
    await callback.answer()
    try:
        telegram_user_id = callback.from_user.id
        student = get_student(telegram_user_id)

        if not student:
            await callback.message.answer(
                "Student profile not found."
            )
            return

        progress = await get_student_progress(
            student_id=student["id"]
        )

        await replace_callback_ui(
            callback,
            format_progress_message(progress),
            back_to_menu(),
        )

    except Exception as error:
        print(
            f"PROGRESS HANDLER ERROR: {error}"
        )
        try:
            await callback.message.answer(
                "Unable to load progress right now.",
                reply_markup=back_to_menu(),
            )
        finally:
            pass
