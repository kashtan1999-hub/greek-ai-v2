"""First contact and an explicit reset for the authenticated Telegram learner."""
from aiogram import Router, F
from aiogram.filters import Command, Filter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.supabase_client import supabase
from services.student_service import get_student
from services.access_service import first_free_lesson
from services.user_session import set_session, clear_session, is_mode

router = Router()

async def welcome(message, student_id, is_new_student=False):
    from services.student_service import get_student_state
    state = get_student_state(student_id) or {}
    found = supabase.table('learner_profiles').select('*').eq('student_id', student_id).execute().data or []
    profile = found[0] if found else {}
    if state.get('current_block') != '1.1' or profile.get('completed'):
        return
    if is_new_student and not found:
        supabase.table('learner_profiles').insert({'student_id':student_id, 'intro_eligible':True}).execute()
    elif not profile.get('intro_eligible'):
        return
    set_session(message.from_user.id, 'onboarding')
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Сразу начать урок', callback_data='skip_introduction')]])
    await message.answer('Привет! Я помогу тебе учить греческий 🙂 Если хочешь, напиши одним сообщением: как тебя называть, зачем тебе греческий и сколько минут в день хочешь учиться. Например: «Анна, для поездки, 15 минут». Это необязательно.', reply_markup=markup)

class Onboarding(Filter):
    async def __call__(self, message: Message):
        return bool(message.from_user and message.text and not message.text.startswith('/') and is_mode(message.from_user.id, 'onboarding'))

@router.message(Onboarding())
async def introduction(message: Message):
    student = get_student(message.from_user.id)
    if not student: return
    text = message.text[:3000]
    profile_rows = supabase.table('learner_profiles').select('*').eq('student_id',student['id']).execute().data or []
    if not profile_rows or not profile_rows[0].get('intro_eligible') or profile_rows[0].get('completed'):
        clear_session(message.from_user.id)
        return
    values = {'preferred_name':student.get('first_name') or '', 'goal':'', 'daily_minutes':None}
    if text.casefold() != 'пропустить':
        from services.profile_parser import parse_introduction
        values.update(await parse_introduction(text))
    supabase.table('learner_profiles').upsert({'student_id': student['id'],
        'introduction': '' if text.casefold() == 'пропустить' else text, 'completed': True, 'intro_eligible':False, **values}, on_conflict='student_id').execute()
    clear_session(message.from_user.id)
    await message.answer('Спасибо! Начнём первый урок.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Продолжить Урок',callback_data='continue_learning')]]))

@router.callback_query(F.data == 'skip_introduction')
async def skip_introduction(callback: CallbackQuery):
    await callback.answer()
    student = get_student(callback.from_user.id)
    if not student: return
    found = supabase.table('learner_profiles').select('*').eq('student_id',student['id']).execute().data or []
    if not found or not found[0].get('intro_eligible') or found[0].get('completed'): return
    supabase.table('learner_profiles').update({'completed':True, 'intro_eligible':False}).eq('student_id',student['id']).execute()
    clear_session(callback.from_user.id)
    from handlers.learning import continue_learning
    await continue_learning(callback)

@router.message(Command('reset_history'))
async def request_reset(message: Message):
    if message.chat.type != 'private': return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Удалить мою учебную историю', callback_data='confirm_reset_history')],
        [InlineKeyboardButton(text='Отмена', callback_data='main_menu')]])
    await message.answer('Начать учёбу заново? Твои ответы, ошибки и учебный прогресс будут удалены. Профиль и подписка сохранятся.', reply_markup=markup)

@router.callback_query(F.data == 'confirm_reset_history')
async def reset_history(callback: CallbackQuery):
    await callback.answer()
    if callback.message.chat.type != 'private': return
    student = get_student(callback.from_user.id)
    first = first_free_lesson()
    if not student or not first: return
    supabase.rpc('reset_learning_history', {'p_student_id': student['id'], 'p_block': first['block'], 'p_topic': first['topic']}).execute()
    clear_session(callback.from_user.id)
    from services.ai_agent import conversation_memory
    conversation_memory.pop(callback.from_user.id, None)
    from services.conversation_log import _log
    _log.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer('Учебная история очищена. Первый урок снова доступен. Отправь /start.')


@router.message(Command('course'))
async def choose_course(message: Message):
    if message.chat.type != 'private': return
    from services.course_sequence import BLOCK_ORDER
    from services.curriculum_service import get_lesson
    buttons = []
    for block in BLOCK_ORDER:
        lesson = get_lesson(block)
        if lesson:
            buttons.append([InlineKeyboardButton(text=f"{block} · {lesson['topic']}"[:64], callback_data=f"course_select:{block}")])
    await message.answer('Выбери урок нового курса. Старые ответы и история сохранятся. Текущий незавершённый урок будет заменён.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith('course_select:'))
async def select_course(callback: CallbackQuery):
    await callback.answer()
    if callback.message.chat.type != 'private': return
    from services.curriculum_service import get_lesson
    from services.course_sequence import BLOCK_ORDER
    from services.student_service import update_state
    from services.access_service import has_access
    block = callback.data.split(':', 1)[1]
    student = get_student(callback.from_user.id)
    lesson = get_lesson(block) if block in BLOCK_ORDER else None
    if not student or not lesson: return
    if not has_access(student, block, lesson['topic']):
        await callback.message.answer('Для этого урока нужна подписка. Первый урок бесплатный.')
        return
    update_state(student['id'], {'current_block':block, 'current_topic':lesson['topic'],
        'active_plan':None, 'next_action':'continue_learning', 'interaction_number':1, 'current_step':1})
    clear_session(callback.from_user.id)
    await callback.message.answer('Урок выбран. Нажми «Продолжить Урок».')
