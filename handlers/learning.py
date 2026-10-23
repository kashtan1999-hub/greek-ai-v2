from services.lesson_stages import build_stages, stage_at, eligible_to_advance
from services.progress_service import save_session_result
from services.russian_ui import russian_text
import logging
import os
import re
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from handlers.tutor import start_tutor_mode, stop_tutor_mode

from keyboards.learning import answer_actions, back_to_menu, lesson_actions
from keyboards.main_menu import get_main_menu
from services.curriculum_service import get_lesson, get_next_lesson, split_message
from services.lesson_agent import generate_lesson
from services.exercise_service import (
    ensure_exercises,
    evaluate,
    get_exercise,
    save_attempt,
    save_learning_error,
)
from services.ui_manager import replace_callback_ui, send_persistent
from services.conversation_log import log_turn, format_recent_turns
from services.student_service import (
    get_student,
    get_student_state,
    next_block,
    normalize_block,
    update_state,
)


router = Router()
logger = logging.getLogger(__name__)
from services.access_service import has_access as _has_access

def _context(telegram_user_id: int) -> tuple[dict | None, dict | None]:
    student = get_student(telegram_user_id)
    if not student:
        return None, None
    return student, get_student_state(student["id"])


def _extract_options(question: str) -> list[str]:
    """Read persisted multiple-choice options from the existing question column."""
    lines = str(question or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().casefold() == "options:":
            start = i + 1
            break
    if start is None:
        return []

    options: list[str] = []
    pattern = re.compile(r"^\s*([A-D])\s*[\)\.]\s*(.+?)\s*$", re.I)
    for line in lines[start:]:
        match = pattern.match(line)
        if not match:
            if options and not line.strip():
                break
            continue
        options.append(match.group(2).strip())
    return options[:4]


async def _ask_exercise(message: Message, plan: dict) -> None:
    ids = plan.get("exercise_ids") or []
    index = int(plan.get("index") or 0)
    if index >= len(ids):
        return

    exercise = get_exercise(ids[index])
    if not exercise:
        raise ValueError("Exercise record was not found.")

    display_question = await russian_text(str(exercise.get("question") or ""))
    options = _extract_options(str(exercise.get("question") or ""))
    stage=stage_at(plan)
    stage_label={'mini':'Мини-практика','understanding':'Проверяем понимание','quiz':'Короткий тест','targeted':'Практика ошибок','recheck':'Проверка после практики'}.get((stage or {}).get('name'),'Упражнение')
    text = (
        f"{stage_label}\n"
        f"✍️ Упражнение {index + 1}/{len(ids)}\n\n"
        f"{display_question}\n\n"
        "👇 Напишите ответ или воспользуйтесь кнопками подсказки и помощи ИИ."
    )
    await message.answer(
        text,
        reply_markup=answer_actions(
            options=options,
            exercise_index=index,
        ),
    )
    if message.from_user:
        log_turn(message.from_user.id, "bot", text)


@router.callback_query(F.data == "continue_learning")
async def continue_learning(callback: CallbackQuery):
    await callback.answer()
    try:
        student, state = _context(callback.from_user.id)
        if not student or not state:
            await callback.message.answer("Please send /start first.")
            return

        from services.user_session import is_mode
        if is_mode(callback.from_user.id, 'onboarding'):
            await callback.message.answer('Сначала ответь на приветствие или напиши «пропустить».')
            return

        block = normalize_block(state.get("current_block"))
        if not _has_access(student, block, state.get("current_topic")):
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            await callback.message.answer(
                "🔒 Первый урок — бесплатное демо.\n\n"
                "Чтобы продолжить обучение после первого урока, нужна подписка "
                "19,90 USD в месяц с автоматическим ежемесячным продлением.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оформить подписку · 19,90 USD/месяц", callback_data="subscription")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
                ]),
            )
            return

        # If a paid period is close to renewal, show one clear learning-flow alert.
        # The authoritative period end is populated by the Stripe webhook.
        if str(student.get("subscription_status") or "").lower() == "active":
            try:
                from services.stripe_service import profile
                from datetime import datetime, timezone
                billing = profile(student["id"])
                period_end = billing.get("current_period_end")
                if period_end:
                    end = datetime.fromisoformat(str(period_end).replace("Z", "+00:00"))
                    days_left = (end - datetime.now(timezone.utc)).days
                    if 0 <= days_left <= 3:
                        await callback.message.answer(
                            f"💳 Внимание: до следующего ежемесячного платежа осталось примерно {days_left} дн. "
                            "Подписка продлится автоматически, если её не отменить.",
                            reply_markup=back_to_menu(),
                        )
            except Exception:
                logger.exception("Could not read subscription renewal date")

        # New client flow: Continue Learning opens a natural AI mentor
        # conversation. The AI receives the authoritative curriculum,
        # progress, weak areas and durable conversation history and decides
        # what the student should learn next. No lesson/action buttons are sent.
        from services.ai_agent import start_learning_conversation
        start_tutor_mode(callback.from_user.id)
        response = await start_learning_conversation(callback.from_user.id)
        for chunk in split_message(response):
            await callback.message.answer(chunk)

    except Exception as error:
        logger.exception("Failed to start conversational learning")
        await callback.message.answer(
            "The learning conversation could not be started. Please try again."
        )


@router.callback_query(F.data == "start_exercises")
async def start_exercises(callback: CallbackQuery):
    await callback.answer()
    # BUG FIX: without this, a student who used "Ask Tutor" earlier and
    # never explicitly tapped "Main Menu" stayed permanently flagged as
    # mid-tutor-conversation. Every exercise answer they typed afterward
    # (including "Question 4/5" style attempts) was then swallowed by
    # the tutor handler instead of reaching the grader.
    stop_tutor_mode(callback.from_user.id)
    try:
        student, state = _context(callback.from_user.id)
        if not student or not state:
            await callback.message.answer("Please send /start first.")
            return

        from services.user_session import is_mode
        if is_mode(callback.from_user.id, 'onboarding'):
            await callback.message.answer('Сначала ответь на приветствие или напиши «пропустить».')
            return
        original_state = dict(state)
        block = normalize_block(state.get("current_block"))
        topic = str(state.get("current_topic") or block)
        if not _has_access(student, block, state.get("current_topic")):
            await callback.message.answer("🔒 Первый урок бесплатный. Для остальных тем нужна подписка: 19,90 USD в месяц.", reply_markup=get_main_menu())
            return
        existing_plan = state.get('active_plan') or {}
        if existing_plan.get('mode') in {'exercise','quiz_retry'}:
            existing_plan['mode']='exercise'
            update_state(student['id'], {'active_plan':existing_plan, 'next_action':'answer'})
            await _ask_exercise(callback.message, existing_plan)
            return
        if existing_plan.get('mode') != 'lesson' or not existing_plan.get('lesson_text'):
            await callback.message.answer('📚 Сначала открой и прочитай текущий урок.', reply_markup=get_main_menu())
            return
        await replace_callback_ui(callback, "⚔ Preparing your exercises…", None)
        exercises = await ensure_exercises(block, topic)
        # Reinforce weak questions first, then vary the remaining order.
        from services.exercise_service import pending_mistakes
        import random
        random.shuffle(exercises)
        weak_ids = {row.get('exercise_id') for row in pending_mistakes(student['id'])}
        exercises.sort(key=lambda row: row['id'] not in weak_ids)
        plan = {
            "mode": "exercise",
            "block": block,
            "stages": build_stages(len(exercises)),
            "stage_scores": {},
            "quiz_hint_used": False,
            "lesson_text": existing_plan.get("lesson_text"),
            "exercise_ids": [row["id"] for row in exercises],
            "index": 0,
            "total_score": 0,
            "hint_level": 0,
            "wrong_attempts": 0,
            "hint_used": False,
            "total_questions": len(exercises),
        }
        update_state(
            student["id"],
            {
                "active_plan": plan,
                "current_step": 2,
                "next_action": "answer",
                "total_questions": len(exercises),
                "exercise_started_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        # Delete only the saved lesson messages, after exercises are ready.
        # The dashboard and other chat messages remain available.
        lesson_plan = original_state.get("active_plan") or {}
        if lesson_plan.get("mode") == "lesson":
            for message_id in lesson_plan.get("message_ids", []):
                try:
                    await callback.bot.delete_message(
                        lesson_plan.get("chat_id", callback.message.chat.id), message_id
                    )
                except Exception:
                    logger.warning("Telegram could not delete lesson message %s", message_id)
        await _ask_exercise(callback.message, plan)
    except Exception as error:
        logger.exception("Failed to start exercises")
        if "No curriculum content found" in str(error):
            await callback.message.answer(
                f"📭 {error}\n\n"
                "This lesson block hasn't been imported into the "
                "curriculum yet (Section 4A is a known gap - see the "
                "README). Try Continue Learning again, or a different "
                "block.",
                reply_markup=back_to_menu(),
            )
        else:
            # BUG FIX: this used to always say "Check OPENAI_API_KEY"
            # no matter what actually failed, which hid the real error.
            # Showing the real exception (also logged in full via
            # logger.exception above, check the server console) makes
            # this diagnosable instead of a dead end.
            await callback.message.answer(
                "Exercises could not be prepared.\n\n"
                f"Details: {error}\n\n"
                "If this is an OpenAI error (key, quota, rate limit) "
                "check OPENAI_API_KEY. Otherwise check the server "
                "console for the full traceback.",
                reply_markup=back_to_menu(),
            )


async def _finish_or_advance(message: Message, student: dict, state: dict, plan: dict):
    plan["index"] = int(plan.get("index") or 0) + 1
    plan["hint_level"] = 0
    plan["wrong_attempts"] = 0
    plan["hint_used"] = False
    ids = plan.get("exercise_ids") or []

    if plan["index"] < len(ids):
        update_state(student["id"], {"active_plan": plan})
        previous=stage_at(plan,plan['index']-1)
        current=stage_at(plan)
        if current and previous and current['name']!=previous['name']:
            await message.answer({'understanding':'Практика завершена. Проверим, что ты понял.', 'quiz':'Понимание проверено. Теперь короткий тест.', 'recheck':'Практика завершена. Теперь попробуй исходные вопросы ещё раз.'}.get(current['name'],'Продолжаем.'))
        await _ask_exercise(message, plan)
        return

    total = float(plan.get("total_score") or 0)
    possible = len(ids)
    if plan.get('stages'):
        quiz=next(stage for stage in plan['stages'] if stage['name'] in {'quiz','recheck'})
        possible=quiz['end']-quiz['start']
        total=plan.get('stage_scores',{}).get(quiz['name'],0)
    percentage = round((total / possible) * 100) if possible else 0

    try:
        save_session_result(student["id"], state.get("current_topic"), plan["block"], percentage, 100, kind="review" if plan.get("return_to") or plan.get("mistake_review") else ("exercise" if eligible_to_advance(plan,percentage) else "practice"))
    except Exception:
        logger.exception("Could not save completion history")

    from services.learning_history import record_completion
    upcoming_lesson = get_next_lesson(plan['block'], state.get('current_topic'))
    if plan.get('mistake_review'):
        from services.learning_history import record_mistake_review
        record_mistake_review(student['id'], plan, state.get('current_topic'), percentage)
        decision = {'review_due_at': datetime.now(timezone.utc).isoformat()}
    else:
        decision = record_completion(student['id'], plan['block'], state.get('current_topic') or plan['block'], plan, percentage, upcoming_lesson)
    if plan.get('return_to'):
        update_state(student['id'], {'active_plan':None,'current_step':1,**plan['return_to']})
        await message.answer(f"Повторение завершено. Результат: {percentage}%. Следующее повторение: {decision['review_due_at'][:10]}.", reply_markup=get_main_menu())
        return
    if eligible_to_advance(plan,percentage):
        next_lesson = get_next_lesson(plan["block"], state.get("current_topic"))
        upcoming = next_lesson["block"] if next_lesson else next_block(plan["block"])
        if upcoming:
            # Fetch the real first lesson from Curriculum before advancing.
            # Never store a placeholder such as "Next lesson" in student_state.

            if not next_lesson:
                update_state(
                    student["id"],
                    {
                        "block_progress": 100,
                        "current_step": 1,
                        "active_plan": None,
                        "next_action": "curriculum_missing",
                    },
                )
                text = (
                    f"🎉 Block {plan['block']} completed!\n\n"
                    f"Score: {percentage}%\n\n"
                    f"The next block ({upcoming}) is not available in Curriculum yet."
                )
            else:
                update_state(
                    student["id"],
                    {
                        "current_block": upcoming,
                        "current_topic": next_lesson["topic"],
                        "current_step": 1,
                        "interaction_number": 1,
                        "active_plan": None,
                        "next_action": f"start_block_{upcoming}",
                        "block_progress": 0,
                        "lesson_progress": 0,
                    },
                )
                text = (
                    f"🎉 Block {plan['block']} completed!\n\n"
                    f"Score: {percentage}%\n"
                    f"Next block: {upcoming}\n"
                    f"Next topic: {next_lesson['topic']}"
                )
        else:
            update_state(
                student["id"],
                {"current_step": 1, "active_plan": None, "next_action": "course_complete"},
            )
            text = f"🏆 A1 course completed!\n\nFinal block score: {percentage}%"
    else:
        update_state(
            student["id"],
            {
                "current_step": 1,
                "active_plan": {**plan, "mode":"quiz_retry", "index":4 if plan.get("stages") else 0, "total_score":0, "stage_scores":{**plan.get("stage_scores",{}),"quiz":0}, "quiz_hint_used":False, "hints_used":False},
                "next_action": "retry_quiz",
                "block_progress": percentage,
            },
        )
        text = (
            f"Score: {percentage}%\n\n" +
            ("Повторите трудные места и попробуйте снова без подсказок." if percentage < 80 else
             "Повторим тест без подсказок. Пройденный материал останется сохранённым.") +
            f"\nСледующее повторение: {decision['review_due_at'][:10]}"
        )

    text += f"\n\nСегодня: {state.get('current_topic') or plan['block']}.\nОшибок: {len(plan.get('mistakes', []))}."
    menu = get_main_menu()
    if eligible_to_advance(plan,percentage) and upcoming_lesson:
        from aiogram.types import InlineKeyboardButton
        menu.inline_keyboard.insert(0,
        [InlineKeyboardButton(text='🔓 Следующий урок',callback_data='next_lesson')]
)
    # Main menu already contains exactly one mistakes button.
    await message.answer(text, reply_markup=menu)


@router.callback_query(F.data == "exercise_hint")
async def exercise_hint(callback: CallbackQuery):
    await callback.answer()
    try:
        student, state = _context(callback.from_user.id)
        plan = (state or {}).get("active_plan") or {}
        if not student or plan.get("mode") != "exercise":
            await callback.message.answer(
                "No active exercise. Choose Continue Learning."
            )
            return

        ids = plan.get("exercise_ids") or []
        index = int(plan.get("index") or 0)
        if index >= len(ids):
            await callback.message.answer("This exercise session is already complete.")
            return

        exercise = get_exercise(ids[index])
        if not exercise:
            raise ValueError("Exercise was not found.")

        answer = str(exercise["correct_answer"])
        level = min(int(plan.get("hint_level") or 0) + 1, 3)
        plan["hint_level"] = level
        plan["hint_used"] = True
        plan["hints_used"] = True
        if (stage_at(plan) or {}).get("name") == "quiz": plan["quiz_hint_used"] = True
        update_state(student["id"], {"active_plan": plan})

        from services.ai_service import guidance_hint
        from services.curriculum_service import lesson_context
        text = "💡 " + await guidance_hint(exercise['question'], answer,
            lesson_context(exercise['block'], state.get('current_topic')))

        options = _extract_options(str(exercise.get("question") or ""))
        await callback.message.answer(
            text,
            reply_markup=answer_actions(
                options=options,
                exercise_index=index,
            ),
        )
    except Exception:
        logger.exception("Failed to provide hint")
        await callback.message.answer(
            "Hint could not be loaded. Please try again."
        )


async def _grade_and_advance(
    message: Message,
    student: dict,
    state: dict,
    plan: dict,
    answer: str,
):
    """Grade one answer, persist it, record mistakes, and move to the next item."""
    if not _has_access(student, str(plan.get("block") or state.get("current_block")), state.get("current_topic")):
        await message.answer("🔒 Для продолжения нужна активная подписка.", reply_markup=get_main_menu())
        return
    ids = plan.get("exercise_ids") or []
    index = int(plan.get("index") or 0)

    if index >= len(ids):
        raise ValueError("Exercise session is already complete.")

    exercise = get_exercise(ids[index])
    if not exercise:
        raise ValueError("Exercise was not found.")

    answer = str(answer or "").strip()
    if not answer:
        await message.answer("Please provide an answer.")
        return

    if message.from_user:
        log_turn(message.from_user.id, "student", answer)

    # Keep the raw-submission audit best-effort: an audit-table/schema/RLS
    # problem must never prevent AI grading or the next exercise from running.
    from services.supabase_client import supabase
    submission = None
    try:
        submission = supabase.table('answer_submissions').insert({
            'student_id': student['id'],
            'exercise_id': exercise['id'],
            'question': exercise['question'],
            'user_answer': answer,
            'block': exercise['block'],
            'topic': state.get('current_topic'),
            'status': 'pending',
        }).execute().data
    except Exception:
        logger.exception('Could not save raw answer submission; continuing to AI grading')

    logger.info('Exercise answer received; starting grader for exercise_id=%s', exercise.get('id'))
    grade = await evaluate(exercise, answer)

    if submission:
        try:
            supabase.table('answer_submissions').update(
                {'status': 'graded', 'result': grade['result']}
            ).eq('id', submission[0]['id']).eq('student_id', student['id']).execute()
        except Exception:
            logger.exception('Could not update answer submission status after grading')

    save_attempt(
        student["id"],
        exercise,
        answer,
        grade,
        bool(plan.get("hint_used")),
        topic=str(state.get("current_topic") or ""),
    )

    if grade['result'] == 'incorrect':
        plan.setdefault('mistakes', []).append({'question': exercise['question'], 'answer': answer, 'correct_answer': exercise['correct_answer']})
    stage=stage_at(plan)
    if grade['result']=='correct' and stage:
        scores=plan.setdefault('stage_scores',{})
        scores[stage['name']]=scores.get(stage['name'],0)+1

    if grade["result"] == "incorrect":
        save_learning_error(
            student["id"],
            exercise,
            answer,
            topic=str(state.get("current_topic") or ""),
        )
    else:
        from services.learning_history import reinforce_mistake
        reinforce_mistake(student['id'], exercise['id'], bool(plan.get('hint_used')))
        plan["total_score"] = (
            float(plan.get("total_score") or 0) + 1
        )

    if grade['result']=='incorrect' and stage and stage['name'] in {'mini','understanding','targeted'}:
        update_state(student['id'], {'active_plan':plan})
        await message.answer('Пока не совсем верно. Посмотри на объяснение: ' + grade.get('feedback','') + '\nПопробуй этот вопрос ещё раз.')
        await _ask_exercise(message,plan)
        return

    label = (
        "✅ Correct"
        if grade["result"] == "correct"
        else "❌ Incorrect"
    )

    await message.answer(
        f"{label}\n{grade['feedback']}"
    )

    await _finish_or_advance(
        message,
        student,
        state,
        plan,
    )


@router.callback_query(F.data.startswith("exercise_option:"))
async def exercise_option(callback: CallbackQuery):
    """Grade a clicked multiple-choice option using the active exercise."""
    await callback.answer()
    if not callback.message:
        return

    try:
        parts = str(callback.data).split(":")
        if len(parts) != 3:
            raise ValueError("Invalid exercise option callback.")

        question_index = int(parts[1])
        option_index = int(parts[2])

        student, state = _context(callback.from_user.id)
        plan = (state or {}).get("active_plan") or {}

        if not student or plan.get("mode") != "exercise":
            await callback.message.answer("No active exercise.")
            return

        current_index = int(plan.get("index") or 0)
        if question_index != current_index:
            await callback.message.answer(
                "This question is no longer active."
            )
            return

        ids = plan.get("exercise_ids") or []
        if current_index >= len(ids):
            await callback.message.answer("This exercise session is complete.")
            return

        exercise = get_exercise(ids[current_index])
        if not exercise:
            raise ValueError("Exercise was not found.")

        options = _extract_options(
            str(exercise.get("question") or "")
        )
        if option_index < 0 or option_index >= len(options):
            raise ValueError("Selected option is invalid.")

        await _grade_and_advance(
            callback.message,
            student,
            state,
            plan,
            options[option_index],
        )
    except Exception as error:
        print("EXERCISE OPTION ERROR:", repr(error))
        logger.exception("Failed to process multiple-choice option")
        await callback.message.answer(
            "Your selected answer could not be checked. Please try again."
        )


@router.message(
    F.text,
    ~F.text.startswith("/ai"),
)
async def receive_exercise_answer(message: Message):
    if not message.from_user:
        return

    try:
        student, state = _context(message.from_user.id)
        plan = (state or {}).get("active_plan") or {}

        if not student or plan.get("mode") != "exercise":
            logger.info(
                'Ignoring text as exercise answer: student_found=%s active_plan_mode=%s',
                bool(student), plan.get('mode'),
            )
            return

        logger.info('Exercise text answer handler reached for telegram_user_id=%s', message.from_user.id)
        await _grade_and_advance(
            message,
            student,
            state,
            plan,
            message.text,
        )

    except Exception as error:
        print("EXERCISE ANSWER ERROR:", repr(error))
        logger.exception("Failed to grade answer")
        await message.answer(
            "Your answer could not be checked. Please try again."
        )


@router.callback_query(F.data == "retry_with_context")
async def retry_with_context(callback: CallbackQuery):
    """
    "Retry": the student got stuck/lost mid-conversation. Rather than
    just re-showing a blank screen, pull the last ~10 messages this
    bot has logged for them (Telegram bots can't fetch arbitrary chat
    history via the API - a bot only ever sees what it's sent/received
    live, so we keep our own rolling log in conversation_log.py) and
    ask the AI to pick the lesson back up in light of that context.
    """
    await callback.answer("🔄 Picking things back up…")
    user_id = callback.from_user.id

    try:
        student, state = _context(user_id)
        plan = (state or {}).get("active_plan") or {}
        transcript = format_recent_turns(user_id)

        from services.ai_agent import process_user_request

        recap_prompt = (
            "The student tapped Retry because the conversation got "
            "confusing or interrupted. Here are our last messages for "
            "context (do not repeat them back verbatim):\n\n"
            f"{transcript}\n\n"
            "In 2-3 short sentences, gently re-orient the student and "
            "tell them what to do next."
        )
        recap = await process_user_request(
            telegram_user_id=user_id,
            user_message=recap_prompt,
        )

        await send_persistent(
            callback.bot,
            callback.message.chat.id,
            f"🔄 {recap}",
            None,
        )
        log_turn(user_id, "bot", recap)

        # If an exercise is in progress, re-show the current question
        # (with working Hint / Ask Tutor / Retry buttons) so the
        # student has something concrete to answer.
        if student and plan.get("mode") == "exercise":
            await _ask_exercise(callback.message, plan)

    except Exception:
        logger.exception("Retry failed")
        await callback.message.answer(
            "Could not refresh the lesson context. Please try Continue "
            "Learning from the main menu.",
            reply_markup=back_to_menu(),
        )


async def _show_exercise_lock(callback):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    await callback.message.answer(
        '🔒 Следующий урок пока закрыт.\n\n✍️ Сначала выполни упражнения и пройди тест текущего урока. После успешного прохождения следующий урок откроется.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✍️ Пройти упражнения',callback_data='start_exercises')],
            [InlineKeyboardButton(text='🏠 Главное меню',callback_data='lesson_main_menu')]]))


@router.callback_query(F.data == "next_lesson")
async def next_lesson(callback: CallbackQuery):
    student, state = _context(callback.from_user.id)
    if not student or not state:
        await callback.answer('Сначала нажми /start.', show_alert=True)
        return
    if str(state.get('next_action') or '').startswith('start_block_') or state.get('next_action')=='course_complete':
        await continue_learning(callback)
        return
    await callback.answer()
    await _show_exercise_lock(callback)

@router.callback_query(F.data == 'practice_mistakes')
async def practice_mistakes(callback: CallbackQuery):
    await callback.answer()
    stop_tutor_mode(callback.from_user.id)
    student, state = _context(callback.from_user.id)
    if not student or not state: return
    from services.exercise_service import pending_mistakes
    from services.supabase_client import supabase
    errors = pending_mistakes(student['id'])
    selected = []
    for error in errors:
        exercise = get_exercise(error.get('exercise_id')) if error.get('exercise_id') else None
        # Older saved mistakes may have the question/answer but no exercise_id.
        # Recover the real stored exercise by its saved question instead of using
        # a hardcoded sample or silently making the review button fail.
        if not exercise and error.get('question'):
            saved_question = str(error['question']).strip()
            recovered = (supabase.table('Exercises').select('*')
                .eq('question', saved_question).limit(1).execute().data or [])
            # Older learning_errors rows may contain the prompt without the
            # multiple-choice options that are appended to Exercises.question.
            if not recovered:
                recovered = (supabase.table('Exercises').select('*')
                    .ilike('question', saved_question + '%').limit(1).execute().data or [])
            # Last-resort normalization handles whitespace/case differences
            # without introducing a hardcoded sample question.
            if not recovered:
                def _question_key(value):
                    value = str(value or '').splitlines()
                    value = '\n'.join(line.strip() for line in value if line.strip())
                    return re.sub(r'\s+', ' ', value).casefold()
                exercise_rows = supabase.table('Exercises').select('*').limit(1000).execute().data or []
                target = _question_key(saved_question)
                for row in exercise_rows:
                    stored = _question_key(row.get('question'))
                    if stored == target or stored.startswith(target + ' options:') or stored.startswith(target):
                        recovered = [row]
                        break
            if recovered:
                exercise = recovered[0]
                error['exercise_id'] = exercise.get('id')
                # Repair legacy mistake rows so future reviews can use the stable ID.
                if error.get('id') and exercise.get('id'):
                    try:
                        (supabase.table('learning_errors')
                            .update({'exercise_id': exercise['id']})
                            .eq('id', error['id'])
                            .eq('student_id', student['id']).execute())
                    except Exception:
                        logger.exception('Could not attach recovered exercise ID to saved mistake')
            # If the old exercise was removed/changed, rebuild a real exercise
            # from the saved mistake itself. This is not a hardcoded sample:
            # it uses this student's saved question and correct answer.
            if not exercise and error.get('question') and error.get('correct_answer'):
                block = str(error.get('block') or state.get('current_block') or '').strip()
                topic = str(error.get('topic') or state.get('current_topic') or block).strip()
                if block:
                    try:
                        payload = {
                            'block': block,
                            'question': str(error['question']).strip(),
                            'correct_answer': str(error['correct_answer']).strip(),
                            'exercise_type': str(error.get('error_type') or 'practice'),
                        }
                        # Add topic only where this project schema supports it.
                        if topic:
                            payload['topic'] = topic
                        created = supabase.table('Exercises').insert(payload).execute().data or []
                        if created:
                            exercise = created[0]
                            error['exercise_id'] = exercise.get('id')
                            if error.get('id') and exercise.get('id'):
                                (supabase.table('learning_errors')
                                    .update({'exercise_id': exercise['id']})
                                    .eq('id', error['id'])
                                    .eq('student_id', student['id']).execute())
                            logger.info('Recovered saved mistake %s as exercise %s', error.get('id'), exercise.get('id'))
                    except Exception:
                        logger.exception('Could not rebuild exercise from saved mistake %s', error.get('id'))
        if exercise and _has_access(student, exercise['block'], error.get('topic')):
            selected.append(error)
    if not selected:
        await callback.message.answer('Нет доступных сохранённых вопросов. Старые ошибки без вопроса можно посмотреть в списке.')
        return
    first = selected[0]
    exercise = get_exercise(first['exercise_id'])
    selected = [e for e in selected if get_exercise(e['exercise_id'])['block'] == exercise['block'] and e['topic'] == first['topic']]
    selected = list({e['exercise_id']:e for e in selected}.values())[:3]
    originals = [get_exercise(e['exercise_id']) for e in selected]
    try:
        from services.exercise_service import targeted_mistake_exercises
        practice = await targeted_mistake_exercises(exercise['block'], first['topic'], originals)
    except Exception:
        logger.exception('Failed to prepare mistake practice')
        await callback.message.answer('Не удалось подготовить практику ошибок. Попробуй ещё раз. Твой урок сохранён.')
        return
    details='\n\n'.join('Вопрос: '+str(row['question'])+'\nТвой ответ: '+str(error.get('user_answer') or error.get('answer') or '—')+'\nВерный ответ: '+str(row['correct_answer']) for row,error in zip(originals,selected))
    for chunk in split_message('Разберём ошибки.\n\n'+details): await callback.message.answer(chunk)
    plan = dict(mode='exercise', block=exercise['block'], index=0, total_score=0, stage_scores={},
        exercise_ids=[e['id'] for e in practice+originals], mistake_review=True,
        stages=[dict(name='targeted',start=0,end=len(practice)),dict(name='recheck',start=len(practice),end=len(practice)+len(originals))],
        return_to={k: state.get(k) for k in ('current_block', 'current_topic', 'next_action', 'active_plan', 'current_step')})
    update_state(student['id'], {'current_block': exercise['block'], 'current_topic': first['topic'], 'active_plan': plan})
    await _ask_exercise(callback.message, plan)


@router.callback_query(F.data == "lesson_ready")
async def lesson_ready(callback: CallbackQuery):
    student, state = _context(callback.from_user.id)
    plan = (state or {}).get('active_plan') or {}
    if not student or plan.get('mode') != 'lesson_intro':
        await callback.answer('Открой текущий урок.', show_alert=True)
        return
    plan['ready'] = True
    update_state(student['id'], {'active_plan': plan})
    await continue_learning(callback)
