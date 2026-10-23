from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Продолжить Урок", callback_data="continue_learning")],
        [InlineKeyboardButton(text="📊 Мой прогресс", callback_data="my_progress"),
         InlineKeyboardButton(text="🔁 Работа над ошибками", callback_data="review_mistakes")],
        [InlineKeyboardButton(text="🎯 Оценка уровня знаний", callback_data="knowledge_assessment")],
        [InlineKeyboardButton(text="💳 Подписка", callback_data="subscription"),
         InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ])
