from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def game_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Продолжить Урок", callback_data="game_continue")],
        [InlineKeyboardButton(text="📊 Прогресс", callback_data="my_progress"),
         InlineKeyboardButton(text="🔁 Работа над ошибками", callback_data="review_mistakes")],
        [InlineKeyboardButton(text="🎯 Оценка уровня знаний", callback_data="knowledge_assessment")],
        [InlineKeyboardButton(text="💎 Премиум", callback_data="subscription"),
         InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ])


def lesson_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продолжить обучение", callback_data="start_lesson")],
        [InlineKeyboardButton(text="🎯 Оценка уровня знаний", callback_data="knowledge_assessment")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="game_home")],
    ])


def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="game_home")]])
