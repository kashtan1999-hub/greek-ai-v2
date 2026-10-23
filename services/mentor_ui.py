"""Optional AI-created choices. Payloads stay server-side and are user-bound."""
import secrets
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from services.user_session import get_session, set_session
from services.curriculum_service import split_message


def normalize_buttons(values):
    if not isinstance(values, list):
        return []
    result = []
    for value in values[:4]:
        if not isinstance(value, dict):
            continue
        label, message = str(value.get('label') or '').strip(), str(value.get('message') or '').strip()
        if label and message and len(label) <= 60 and len(message) <= 1000:
            result.append({'label': label, 'message': message})
    return result


async def send_mentor_reply(message, user_id, result):
    buttons = normalize_buttons(result.get('buttons'))
    token = secrets.token_hex(6)
    set_session(user_id, 'tutor_chat', choice_token=token, choices=buttons)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b['label'], callback_data=f'mentor_choice:{token}:{i}')]
        for i, b in enumerate(buttons)
    ]) if buttons else None
    if (result.get('action_result') or {}).get('result') == 'payment_required':
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💳 Подписка', callback_data='subscription')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu')],
        ])
    chunks = split_message(result['reply'])
    for i, chunk in enumerate(chunks):
        await message.answer(chunk, reply_markup=markup if i == len(chunks)-1 else None)
    if result.get('action') == 'assessment':
        from handlers.assessment import begin_assessment
        await begin_assessment(message, announce=True, user_id=user_id)
