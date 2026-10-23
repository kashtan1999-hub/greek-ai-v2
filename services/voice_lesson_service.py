from services.teaching_policy import SIMPLE_TEACHING

import os
import tempfile
from openai import AsyncOpenAI

from services.supabase_client import supabase
from services.lesson_agent import generate_lesson

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def get_current_lesson_text(student_id: int):
    from services.database_agent import get_current_lesson
    return await get_current_lesson(student_id)


async def create_voice_lesson(student_id: int, telegram_user_id: int):
    lesson = await get_current_lesson_text(student_id)

    if not lesson:
        return None

    # Generate voice from the same AI lesson flow.
    # Do not directly convert raw Curriculum content.
    from services.student_service import get_student_state
    state = get_student_state(student_id) or {}
    from services.curriculum_service import require_content
    _, digest = require_content(lesson)
    plan = state.get('active_plan') or {}
    ai_lesson = plan.get('lesson_text') if plan.get('source_digest') == digest and plan.get('generator_version') == 'full-russian-v3' else None
    if not ai_lesson:
        ai_lesson = await generate_lesson(telegram_user_id, lesson_row=lesson)

    prompt = f"""
Convert this AI-generated Greek lesson into a clear spoken audio lesson for the student.

Lesson:
{ai_lesson}

Rules:
- Preserve ALL teaching points from the AI lesson. Do not omit important information.
- Keep the same current block and topic.
- Follow the same order as the lesson so the student can follow it while listening.
- Explain every required point from the lesson, including all letters, sounds,
  vocabulary, grammar points, examples, meanings and practice instructions that
  are actually present.
- Use plain Russian understandable to a 12-year-old. Explain difficult words with concrete examples.
- Speak/write naturally for audio: short sentences, clear pauses, and one idea at a time.
- For Greek examples, say the Greek first and then explain the meaning in Russian.
- Explain pronunciation clearly when pronunciation is part of the lesson.
- Do not introduce unrelated topics or future grammar.
- Do not turn a complete lesson into a short summary. The audio must teach the
  complete supplied lesson content.
- Do not add markdown, emojis, headings, tables, or symbols that should be read aloud.
- End with the lesson's practice task or a short reminder to practice the material.
"""

    text = (
        await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            temperature=0.15,
            messages=[{"role": "system", "content": SIMPLE_TEACHING},{"role": "user", "content": prompt}],
        )
    ).choices[0].message.content.strip()

    audio = await client.audio.speech.create(
        model=os.getenv("OPENAI_TTS_MODEL", "tts-1"),
        voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
        input=text,
        response_format="opus",
        speed=0.8,
    )

    path = tempfile.NamedTemporaryFile(
        suffix=".ogg",
        delete=False
    ).name

    audio.stream_to_file(path)

    return path, lesson
