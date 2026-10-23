from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def lesson_actions() -> InlineKeyboardMarkup:
    pairs = [[("🔒 Следующий урок", "next_lesson"), ("🎧 Аудиоурок", "voice_lesson")],
             [("🎤 Разговорная практика", "speaking_practice"), ("💡 Помощь ИИ", "ai_tutor_help")],
             [("✍️ Начать упражнения", "start_exercises"), ("🏠 Главное меню", "lesson_main_menu")]]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c) for t,c in row] for row in pairs])


def answer_actions(options: list[str] | None = None, exercise_index: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if options:
        letters = "ABCD"
        option_buttons = []
        for index, option in enumerate(options[:4]):
            label = f"{letters[index]}) {str(option).strip()}"
            option_buttons.append(
                InlineKeyboardButton(
                    text=label[:64],
                    callback_data=f"exercise_option:{exercise_index if exercise_index is not None else -1}:{index}",
                )
            )

        # Put two options on each row for compact Telegram layout.
        for index in range(0, len(option_buttons), 2):
            rows.append(option_buttons[index:index + 2])

    rows.append(
        [
            InlineKeyboardButton(
                text="💡 Подсказка",
                callback_data="exercise_hint",
            ),
            InlineKeyboardButton(
                text="🤖 Спросить ИИ",
                callback_data="ask_tutor",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Повторить",
                callback_data="retry_with_context",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🏠 Главное меню",
                callback_data="main_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="main_menu",
                )
            ]
        ]
    )
