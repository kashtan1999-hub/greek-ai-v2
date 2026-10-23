from aiogram.exceptions import TelegramBadRequest
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from services.ai_agent import generate_assessment_questions, determine_assessment_level
from services.student_service import get_student, get_student_state, update_state
from services.conversation_log import log_turn
from services.supabase_client import supabase
from services.user_session import get_session, set_session, clear_session

router = Router()

QUESTIONNAIRE = [
    ("Как хорошо ты уже знаешь греческий?", ["Почти не знаю", "Знаю основы", "Могу немного говорить", "Могу свободно общаться"]),
    ("Что ты уже умеешь?", ["Буквы и несколько слов", "Простые фразы", "Простые разговоры", "Могу поддержать разговор"]),
    ("Что лучше всего описывает твою цель?", ["Начать с нуля", "Уверенный A1", "Перейти к A2+", "Проверить текущий уровень"]),
]


def _questionnaire_markup(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"assessment_self:{index}:{choice}")]
        for choice, label in enumerate(QUESTIONNAIRE[index][1])
    ])



def _test_markup(index: int, options: list[str]) -> InlineKeyboardMarkup:
    rows = []

    for choice in range(0, len(options), 2):
        row = [
            InlineKeyboardButton(
                text=str(options[choice])[:64],
                callback_data=f"assessment_answer:{index}:{choice}",
            )
        ]

        if choice + 1 < len(options):
            row.append(
                InlineKeyboardButton(
                    text=str(options[choice + 1])[:64],
                    callback_data=f"assessment_answer:{index}:{choice + 1}",
                )
            )

        rows.append(row)

    return InlineKeyboardMarkup(inline_keyboard=rows)



async def begin_assessment(
    message: Message,
    announce: bool = False,
    user_id: int | None = None,
):
    # For a button callback, message.from_user is the bot.
    # callback.from_user is the actual student who pressed the button.
    actual_user_id = user_id if user_id is not None else (
        message.from_user.id if message.from_user else None
    )
    if actual_user_id is None:
        return

    student = get_student(actual_user_id)
    if not student:
        await message.answer("Please send /start first.")
        return

    set_session(actual_user_id, "assessment_questionnaire", answers=[])
    prefix = "🎯 Knowledge Level Assessment\n\n" if announce else ""
    await message.answer(
        prefix + QUESTIONNAIRE[0][0],
        reply_markup=_questionnaire_markup(0),
    )


@router.callback_query(F.data == "knowledge_assessment")
async def knowledge_assessment(callback: CallbackQuery):
    await callback.answer()
    # Use the callback sender, not callback.message.from_user (the bot).
    await begin_assessment(callback.message, user_id=callback.from_user.id)


@router.callback_query(F.data.startswith("assessment_self:"))
async def assessment_self(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = get_session(user_id)
    if session.get("mode") != "assessment_questionnaire":
        await callback.answer("Start the assessment from the menu.", show_alert=True)
        return
    try:
        _, index, choice = callback.data.split(":")
        index, choice = int(index), int(choice)
    except Exception:
        await callback.answer("Invalid assessment step.", show_alert=True)
        return
    answers = list(session.get("answers") or [])
    selected = QUESTIONNAIRE[index][1][choice]
    answers.append(selected)
    log_turn(user_id, "student", f"Assessment questionnaire: {QUESTIONNAIRE[index][0]} → {selected}")
    if index + 1 < len(QUESTIONNAIRE):
        session["answers"] = answers
        set_session(user_id, "assessment_questionnaire", answers=answers)
        await callback.message.edit_text(QUESTIONNAIRE[index + 1][0], reply_markup=_questionnaire_markup(index + 1))
        await callback.answer()
        return

    student = get_student(user_id)
    if not student:
        await callback.answer("Please send /start first.", show_alert=True)
        return
    await callback.answer("Creating your assessment…")
    try:
        questions = await generate_assessment_questions(answers, student["id"])
        set_session(user_id, "assessment_test", questionnaire=answers, questions=questions, answers=[], index=0)
        q = questions[0]
        await callback.message.answer(
            f"🎯 Assessment — 1/{len(questions)}\n\n{q['question']}",
            reply_markup=_test_markup(0, q["options"]),
        )
        
    except Exception as error:
        print("ASSESSMENT CREATE ERROR:", repr(error))
        clear_session(user_id)
        await callback.message.answer("The assessment could not be created. Please try again.")


@router.callback_query(F.data.startswith("assessment_answer:"))
async def assessment_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = get_session(user_id)
    if session.get("mode") != "assessment_test":
        await callback.answer("This assessment is no longer active.", show_alert=True)
        return
    try:
        _, index, choice = callback.data.split(":")
        index, choice = int(index), int(choice)
    except Exception:
        await callback.answer("Invalid answer.", show_alert=True)
        return
    questions = session.get("questions") or []
    if index >= len(questions):
        await callback.answer("Invalid question.", show_alert=True)
        return
    answers = list(session.get("answers") or [])
    while len(answers) <= index:
        answers.append(-1)
    answers[index] = choice
    log_turn(user_id, "student", f"Assessment question {index + 1}: {questions[index]['question']} → {questions[index]['options'][choice]}")
    session["answers"] = answers
    next_index = index + 1
    await callback.answer()

    if next_index < len(questions):
        q = questions[next_index]
        set_session(user_id, "assessment_test", questionnaire=session.get("questionnaire") or [], questions=questions, answers=answers, index=next_index)
        await callback.message.edit_text(
            f"🎯 Assessment — {next_index + 1}/{len(questions)}\n\n{q['question']}",
            reply_markup=_test_markup(next_index, q["options"]),
        )
        return

    student = get_student(user_id)
    if not student:
        clear_session(user_id)
        await callback.message.answer("Please send /start first.")
        return
    try:
        result = await determine_assessment_level(session.get("questionnaire") or [], questions, answers, student["id"])
        # Score deterministically from the stored correct_index values. The AI only
        # interprets the verified result; it cannot invent mistakes.
        correct_count = sum(
            1 for i, q in enumerate(questions)
            if i < len(answers) and answers[i] == int(q.get("correct_index", -1))
        )
        total_count = len(questions)
        percentage = round(correct_count / total_count * 100) if total_count else 0
        try:
            from services.progress_service import save_session_result
            save_session_result(student["id"], "Knowledge Assessment", "assessment", percentage, 100, kind="assessment")
            from services.activity_service import record_activity
            record_activity(student["id"], "assessment_completed", None, "Knowledge Assessment", {
                "source": "knowledge_assessment", "correct": correct_count, "total": total_count,
                "percentage": percentage, "level": result["level"],
            })
            # Persist only verified assessment mistakes.
            for i, q in enumerate(questions):
                if i >= len(answers) or answers[i] == int(q.get("correct_index", -1)):
                    continue
                options = q.get("options") or []
                wrong = options[answers[i]] if 0 <= answers[i] < len(options) else ""
                correct = options[int(q.get("correct_index", -1))] if 0 <= int(q.get("correct_index", -1)) < len(options) else ""
                if not wrong or not correct:
                    continue
                question_text = str(q.get("question") or "")
                existing = (supabase.table("learning_errors").select("id,count")
                            .eq("student_id", student["id"]).eq("topic", "Knowledge Assessment")
                            .eq("question", question_text).eq("resolved", False).limit(1).execute().data or [])
                payload = {
                    "student_id": student["id"], "topic": "Knowledge Assessment",
                    "error_type": "assessment", "exercise_id": None,
                    "question": question_text, "wrong_answer": str(wrong),
                    "correct_answer": str(correct), "resolved": False,
                    "review_sessions_remaining": 2, "retention_successes": 0,
                    "last_correct_at": None,
                }
                if existing:
                    supabase.table("learning_errors").update({
                        **payload, "count": int(existing[0].get("count") or 0) + 1
                    }).eq("id", existing[0]["id"]).eq("student_id", student["id"]).execute()
                else:
                    supabase.table("learning_errors").insert({**payload, "count": 1}).execute()
        except Exception as save_error:
            print("ASSESSMENT HISTORY SAVE ERROR:", repr(save_error))
        update_state(student["id"], {"level": result["level"]})
        try:
            supabase.table("learner_profiles").upsert({
                "student_id": student["id"],
                "introduction": "\n".join(session.get("questionnaire") or []),
                "completed": True,
            }, on_conflict="student_id").execute()
        except Exception as profile_error:
            print("ASSESSMENT PROFILE SAVE ERROR:", repr(profile_error))
        clear_session(user_id)
        log_turn(user_id, "bot", f"Knowledge assessment result: {result['level']} ({result['confidence']}). {result['summary']}")
        await callback.message.edit_text(
            f"🎯 Assessment complete\n\nEstimated level: {result['level']}\nConfidence: {result['confidence']}\n\n{result['summary']}\n\nYou can now use Continue Learning and I’ll adapt the conversation to your level."
        )
    except Exception as error:
        print("ASSESSMENT RESULT ERROR:", repr(error))
        clear_session(user_id)
        await callback.message.answer("The assessment result could not be calculated. Please try again.")
