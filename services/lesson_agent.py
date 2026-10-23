import os, json
from openai import AsyncOpenAI
from services.database_agent import get_current_lesson, get_student_id_by_telegram, get_student_progress, get_weak_topics
from services.curriculum_service import require_content
from services.content_lesson import render_content_lesson

client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
OPENAI_MODEL = os.getenv('OPENAI_MODEL','gpt-4.1-mini')

async def generate_lesson(telegram_user_id: int, lesson_row: dict | None = None) -> str:
    student_id = await get_student_id_by_telegram(telegram_user_id)
    if not student_id: raise RuntimeError('Student profile not found. Send /start.')
    lesson = lesson_row if lesson_row is not None else await get_current_lesson(student_id)
    material, digest = require_content(lesson)
    from services.learning_history import context
    saved = context(student_id)
    progress = await get_student_progress(student_id)
    weak = await get_weak_topics(student_id)
    learner = json.dumps({'saved_profile_and_history':saved,'progress':progress,'weak_areas':weak},ensure_ascii=False,default=str)
    rendered = await render_content_lesson(client, OPENAI_MODEL, material, learner)
    # Topic is display-only. The lesson itself was generated and validated from
    # Curriculum.content above; topic/title cannot select or replace the source.
    title = lesson.get('topic') or ''
    return f"📚 {lesson['block']} · {title}\n\n{rendered}"
