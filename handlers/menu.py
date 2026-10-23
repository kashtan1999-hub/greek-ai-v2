from services.dashboard_menu import send_dashboard
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.learning import back_to_menu
from keyboards.main_menu import get_main_menu
from services.exercise_service import pending_mistakes
from services.progress_service import get_student_progress, format_progress_message
from services.student_service import get_student, get_student_state
from services.ui_manager import replace_callback_ui


router = Router()
logger = logging.getLogger(__name__)


def _identity(callback: CallbackQuery) -> tuple[dict | None, dict | None]:
    student = get_student(callback.from_user.id)
    if not student:
        return None, None
    return student, get_student_state(student["id"])


@router.callback_query(F.data == "my_progress")
async def my_progress(callback: CallbackQuery):
    await callback.answer()
    try:
        student, state = _identity(callback)
        if not student or not state:
            await callback.message.answer("Please send /start first.")
            return

        await send_dashboard(callback.message, student["id"], back_to_menu(), "📊 Learning Progress")
    except Exception:
        logger.exception("Failed to show progress")
        await replace_callback_ui(callback, "Progress could not be loaded. Please try again.", back_to_menu())


@router.callback_query(F.data == "review_mistakes")
async def review_mistakes(callback: CallbackQuery):
    await callback.answer()
    try:
        student, _ = _identity(callback)
        if not student:
            await callback.message.answer("Please send /start first.")
            return

        mistakes = pending_mistakes(student["id"])
        if not mistakes:
            text = "🔁 Review Mistakes\n\nNo mistakes recorded yet. Complete more exercises and I will create review missions for you."
        else:
            rows = []
            for index, item in enumerate(mistakes, 1):
                rows.append(
                    f"{index}. {item.get('topic')}\n"
                    f"Вопрос: {item.get('question') or 'Старый вопрос не сохранён'}\n"
                    f"Ваш ответ: {item.get('wrong_answer')}\n"
                    f"Correct answer: {item.get('correct_answer')}"
                )
            text = "🔁 Review Mistakes\n\n" + "\n\n".join(rows)

        from services.curriculum_service import split_message
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✍️ Повторить ошибки', callback_data='practice_mistakes')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu')]]) if mistakes else back_to_menu()
        for chunk in split_message(text):
            await callback.message.answer(chunk, reply_markup=markup)
    except Exception:
        logger.exception("Failed to show mistakes")
        await replace_callback_ui(callback, "Mistakes could not be loaded. Please try again.", back_to_menu())


@router.callback_query(F.data == "subscription")
async def subscription(callback: CallbackQuery):
    await callback.answer()
    student, _ = _identity(callback)
    if not student:
        await callback.message.answer("Please send /start first.")
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from services.stripe_service import payments_ready, profile, sync_subscription, create_checkout, create_portal, StripeRequestError, _missing_resource, save_profile
    if not payments_ready():
        await callback.message.answer("💳 Подписка: 19,90 USD в месяц.\n\nПервый урок доступен бесплатно. Оплата пока недоступна — настройка платежей ещё не завершена.", reply_markup=back_to_menu())
        return
    try:
        billing = profile(student['id'])
        if billing.get('subscription_id'):
            try:
                await sync_subscription(billing['subscription_id'])
            except StripeRequestError as error:
                if not _missing_resource(error): raise
                save_profile(student['id'], {'subscription_id':None,'checkout_request_id':None})
                billing['subscription_id']=None

        # "Check payment" must also reconcile a completed Checkout session
        # when the webhook has not reached the bot yet.
        if not billing.get('subscription_id') and billing.get('checkout_session_id'):
            try:
                from services.stripe_service import stripe_request
                session = await stripe_request('GET', 'checkout/sessions/' + billing['checkout_session_id'], {'expand[]': 'subscription'})
                sub = session.get('subscription')
                if isinstance(sub, dict):
                    sub_id = sub.get('id')
                else:
                    sub_id = sub
                if sub_id:
                    await sync_subscription(sub_id)
                    billing = profile(student['id'])
            except StripeRequestError as error:
                if not _missing_resource(error):
                    raise

        student = get_student(callback.from_user.id)
        course_access = str(student.get('subscription_status') or '').lower() == 'active'
        active = course_access and bool(billing.get('customer_id') and billing.get('subscription_id'))
        url = await (create_portal(student['id']) if active else create_checkout(student['id'], callback.from_user.id))
        next_payment = ''
        if active and billing.get('current_period_end'):
            try:
                next_payment = datetime.fromisoformat(str(billing['current_period_end']).replace('Z', '+00:00')).strftime('%d.%m.%Y')
            except ValueError:
                next_payment = ''
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💳 Управлять подпиской' if active else '💳 Подписаться · 19,90 USD/месяц', url=url)],
            [InlineKeyboardButton(text='🔄 Проверить оплату', callback_data='subscription')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='main_menu')],
        ])
        active_text = (
            '✅ Подписка активна. Стоимость: 19,90 USD в месяц.'
            + (f' Следующее списание: {next_payment}.' if next_payment else '')
        )
        inactive_text = (
            '⚠️ Доступ отмечен как активный, но платёжная запись Stripe ещё не синхронизирована. '
            'Нажми «Проверить оплату».'
            if course_access else
            'Первый урок (1.1) бесплатный. Все следующие уроки требуют подтверждённой подписки.'
        )
        await callback.message.answer(
            '💎 Подписка на курс\n\n19,90 USD в месяц. Автоматическое продление до отмены.\n\n'
            + (active_text if active else inactive_text),
            reply_markup=markup
        )
    except Exception:
        logger.exception('Could not prepare Stripe subscription')
        await callback.message.answer('Не удалось открыть оплату. Попробуйте позже или обратитесь в поддержку.', reply_markup=back_to_menu())


@router.callback_query(F.data == "help")
async def help_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "ℹ️ Help\n\n"
        "📚 Continue Learning — chat naturally with your AI Greek mentor.\n"
        "📊 My Progress — view course completion and score.\n"
        "🔁 Review Mistakes — see answers scheduled for review.\n"
        "🎯 Knowledge Level Assessment — check your current level at any time.\n"
        "💳 Subscription — check your access status.\n\n"
        "Send /start at any time to reopen the main menu.",
        reply_markup=back_to_menu(),
    )

