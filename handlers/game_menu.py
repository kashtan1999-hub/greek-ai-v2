from aiogram import Router, F
from aiogram.types import CallbackQuery
from keyboards.game_menu import game_main_menu
from services.student_service import get_student
from services.dashboard_menu import send_dashboard
from handlers.tutor import stop_tutor_mode

router = Router()

@router.callback_query(F.data.in_({"lesson_main_menu", "game_home", "main_menu"}))
async def main_menu(callback: CallbackQuery):
    await callback.answer()
    stop_tutor_mode(callback.from_user.id)
    student = get_student(callback.from_user.id)
    if not student:
        await callback.message.answer("Please send /start first.")
        return
    await send_dashboard(callback.message, student["id"], game_main_menu())

@router.callback_query(F.data.in_({"game_continue", "start_lesson"}))
async def start_lesson(callback: CallbackQuery):
    from handlers.learning import continue_learning
    await continue_learning(callback)
