import asyncio
from collections import defaultdict

from aiogram.types import CallbackQuery

_ui_messages = defaultdict(list)


async def clear_previous_ui(bot, chat_id: int):
    messages = _ui_messages.get(chat_id, [])

    for message_id in messages:
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    _ui_messages[chat_id] = []


async def magic_transition(bot, chat_id: int):
    """
    Telegram does not support real animations.
    This creates a premium multi-frame transition effect.
    """

    try:
        effect = await bot.send_message(
            chat_id,
            "✨ Preparing your learning space..."
        )

        await asyncio.sleep(0.3)

        await effect.edit_text(
            "✨ 🪄 Updating your progress..."
        )

        await asyncio.sleep(0.3)

        await effect.edit_text(
            "🪄 Loading..."
        )

        await asyncio.sleep(0.4)

        await bot.delete_message(
            chat_id,
            effect.message_id
        )

    except Exception:
        pass


async def send_ui(
    bot,
    chat_id: int,
    text: str,
    reply_markup=None
):

    await magic_transition(bot, chat_id)

    await clear_previous_ui(bot, chat_id)

    msg = await bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup
    )

    _ui_messages[chat_id].append(msg.message_id)

    return msg


async def send_persistent(
    bot,
    chat_id: int,
    text: str,
    reply_markup=None
):
    """
    Like send_ui, but does NOT delete any previous messages.

    Use this for anything the student should still be able to scroll
    back and read afterwards (AI Tutor replies, hints, exercise
    feedback). send_ui/replace_callback_ui are destructive by design
    (they clear the screen for menu transitions) - they should stay
    reserved for actual menu/screen changes, not for conversation turns.
    """

    msg = await bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup
    )

    return msg


async def replace_callback_ui(
    callback: CallbackQuery,
    text: str,
    reply_markup=None
):

    chat_id = callback.message.chat.id

    await magic_transition(
        callback.bot,
        chat_id
    )

    await clear_previous_ui(
        callback.bot,
        chat_id
    )


    msg = await callback.bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup
    )

    _ui_messages[chat_id].append(
        msg.message_id
    )

    return msg
