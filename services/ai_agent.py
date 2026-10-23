from services.teaching_policy import SIMPLE_TEACHING
import json
import os
import re

from dotenv import load_dotenv
from openai import AsyncOpenAI

from services.database_agent import (
    get_student_progress,
    get_weak_topics,
    get_current_lesson,
    get_student_id_by_telegram,
)
from services.conversation_log import log_turn, recent_turns
from services.student_service import get_student, get_student_state, update_state
from services.course_sequence import BLOCK_ORDER
from services.supabase_client import supabase
from services.curriculum_service import get_next_lesson, get_lesson
from services.access_service import has_access

load_dotenv()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY missing in .env file")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)


def _parse_json(text: str):
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


async def _build_context(student_id: int, extra: str = "") -> str:
    lesson = await get_current_lesson(student_id)
    from services.curriculum_service import require_content
    material, _ = require_content(lesson)
    progress = await get_student_progress(student_id)
    weak = await get_weak_topics(student_id)
    from services.learning_history import context as saved_context
    return (
        "AUTHORITATIVE CURRENT CURRICULUM:\n" + material +
        "\n\nSTUDENT PROGRESS:\n" + json.dumps(progress, ensure_ascii=False, default=str) +
        "\n\nWEAK AREAS:\n" + json.dumps(weak, ensure_ascii=False, default=str) +
        "\n\nLEARNING HISTORY:\n" + saved_context(student_id) +
        ("\n\nEXTRA CONTEXT:\n" + extra if extra else "")
    )



def _billing_context(student_id: int) -> dict:
    """Expose only authoritative billing facts to the mentor; never card data."""
    try:
        from services.stripe_service import profile, AMOUNT, CURRENCY, INTERVAL
        p = profile(student_id)
        student = get_student_by_id(student_id)
        status = str((student or {}).get("subscription_status") or "free").lower()
        return {
            "access": "paid" if status == "active" else "free",
            "subscription_status": status,
            "plan": f"{AMOUNT/100:.2f} {CURRENCY.upper()}/{INTERVAL}",
            "current_period_end": p.get("current_period_end"),
            "last_paid_at": p.get("last_paid_at"),
            "previous_subscription_status": p.get("previous_status"),
            "status_changed_at": p.get("status_changed_at"),
        }
    except Exception:
        return {"access": "unknown", "subscription_status": "unknown", "plan": "19.90 USD/month"}


def get_student_by_id(student_id: int):
    try:
        rows = supabase.table("Students").select(
            "id,first_name,subscription_status,trial_expires_at"
        ).eq("id", student_id).limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _can_advance_conversation(student_id: int, data: dict | None = None) -> bool:
    """Require current-lesson evidence, not an arbitrary global message count."""
    state = get_student_state(student_id) or {}
    interactions = int(state.get("interaction_number") or 0)
    data = data or {}
    confirmed = bool(data.get("completion_confirmed"))
    # At least two current learning interactions are required. The model must
    # explicitly confirm that it has enough evidence to finish the lesson.
    return interactions >= 2 and confirmed


def recent_turns_for_student(student_id: int) -> list[dict]:
    try:
        rows = supabase.table(
            "conversation_history"
        ).select("role,content,created_at").eq("student_id", student_id).order(
            "created_at", desc=True
        ).limit(40).execute().data or []
        rows.reverse()
        return [{"role": r.get("role"), "text": r.get("content", "")} for r in rows]
    except Exception:
        return []


async def _execute_ai_action(telegram_user_id: int, student_id: int, action: str, data: dict) -> dict:
    """Controlled server-side actions requested by the AI mentor."""
    action = str(action or "none").lower()
    if action == "none":
        return {"executed": False}

    student = get_student(telegram_user_id)
    state = get_student_state(student_id) if student else None
    if not student or not state:
        return {"executed": False, "reason": "student_not_found"}

    block = str(state.get("current_block") or "")
    if action == "open_lesson":
        target_block = str(data.get("block") or "").strip()
        if target_block not in BLOCK_ORDER:
            return {"executed": False, "reason": "invalid_lesson"}
        lesson = get_lesson(target_block)
        if not lesson:
            return {"executed": False, "reason": "lesson_not_found"}
        from services.access_service import has_access
        if not has_access(student, target_block, lesson.get("topic")):
            return {"executed": False, "result": "payment_required", "next_block": target_block, "next_topic": lesson.get("topic")}
        update_state(student_id, {
            "current_block": target_block, "current_topic": lesson.get("topic"),
            "current_step": 1, "interaction_number": 1, "active_plan": None,
            "next_action": "continue_learning", "block_progress": 0, "lesson_progress": 0,
        })
        return {"executed": True, "result": "opened", "next_block": target_block, "next_topic": lesson.get("topic")}

    if action == "advance_lesson":
        if not _can_advance_conversation(student_id, data):
            return {"executed": False, "reason": "not_enough_learning_evidence"}
        next_lesson = get_next_lesson(block, state.get("current_topic"))
        if not next_lesson:
            return {"executed": False, "reason": "no_next_lesson"}
        # Payment is checked before changing the saved pointer. A free learner
        # remains on the completed free lesson until the required subscription is active.
        from services.access_service import has_access
        paid = has_access(student, next_lesson["block"], next_lesson.get("topic"))
        if not paid:
            return {
                "executed": False,
                "result": "payment_required",
                "next_block": next_lesson["block"],
                "next_topic": next_lesson.get("topic"),
            }
        try:
            from services.progress_service import save_session_result
            save_session_result(
                student_id, state.get("current_topic") or block, block, 100, 100, kind="lesson"
            )
            from services.activity_service import record_activity
            record_activity(student_id, "lesson_completed", block, state.get("current_topic"), {"source": "ai_mentor"})
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Could not save conversational lesson completion")
        update_state(student_id, {
            "current_block": next_lesson["block"],
            "current_topic": next_lesson.get("topic"),
            "current_step": 1,
            "interaction_number": 1,
            "active_plan": None,
            "next_action": "continue_learning",
            "block_progress": 0,
            "lesson_progress": 0,
        })
        return {"executed": True, "result": "advanced", "next_block": next_lesson["block"], "next_topic": next_lesson.get("topic")}

    if action == "update_profile":
        level = str(data.get("level") or "").upper().strip()
        if level and level not in {"A0", "A1", "A2", "B1", "B2", "C1", "C2"}:
            return {"executed": False, "reason": "invalid_level"}
        values = {"level": level} if level else {}
        if not values:
            return {"executed": False, "reason": "no_profile_values"}
        update_state(student_id, values)
        return {"executed": True, "result": "profile_updated", "values": values}

    if action == "update_progress":
        values = {}
        for key in ("current_step", "lesson_progress", "block_progress"):
            if key in data:
                try:
                    value = int(data[key])
                except (TypeError, ValueError):
                    return {"executed": False, "reason": f"invalid_{key}"}
                if key != "current_step" and not 0 <= value <= 100:
                    return {"executed": False, "reason": f"invalid_{key}_range"}
                if key == "current_step" and value < 1:
                    return {"executed": False, "reason": "invalid_current_step"}
                values[key] = value
        if "next_action" in data and str(data.get("next_action")) in {"continue_learning", "answer", "payment_required", "assessment"}:
            values["next_action"] = str(data.get("next_action"))
        if not values:
            return {"executed": False, "reason": "no_progress_values"}
        update_state(student_id, values)
        return {"executed": True, "result": "progress_updated", "values": values}

    if action == "start_exercise":
        # Natural-chat exercise: the AI supplies the actual question in its reply.
        # This action only persists the learning state/activity; it does not invoke
        # the legacy button-driven exercise UI.
        step = max(2, int(state.get("current_step") or 1))
        update_state(student_id, {"current_step": step, "next_action": "answer"})
        try:
            from services.activity_service import record_activity
            record_activity(student_id, "exercise_started", block, state.get("current_topic"), {"source": "ai_mentor", "mode": "natural_chat"})
        except Exception:
            pass
        return {"executed": True, "result": "exercise_started"}

    if action == "record_mistake":
        mistake = data.get("mistake")
        if not isinstance(mistake, dict):
            return {"executed": False, "reason": "invalid_mistake"}
        question = str(mistake.get("question") or "").strip()
        wrong = str(mistake.get("wrong_answer") or "").strip()
        correct = str(mistake.get("correct_answer") or "").strip()
        topic = str(state.get("current_topic") or block).strip()
        if not question or not wrong or not correct:
            return {"executed": False, "reason": "incomplete_mistake"}
        try:
            from services.supabase_client import supabase
            existing = supabase.table("learning_errors").select("id,count").eq(
                "student_id", student_id
            ).eq("topic", topic).eq("question", question).eq("resolved", False).limit(1).execute().data or []
            payload = {
                "question": question,
                "wrong_answer": wrong,
                "correct_answer": correct,
                "last_seen_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "review_sessions_remaining": 2,
                "resolved": False,
                "retention_successes": 0,
                "last_correct_at": None,
            }
            if existing:
                supabase.table("learning_errors").update({
                    **payload, "count": int(existing[0].get("count") or 0) + 1
                }).eq("id", existing[0]["id"]).eq("student_id", student_id).execute()
            else:
                supabase.table("learning_errors").insert({
                    "student_id": student_id, "topic": topic,
                    "error_type": "ai_conversation", "count": 1,
                    "exercise_id": None, **payload
                }).execute()
            return {"executed": True, "result": "mistake_saved"}
        except Exception as error:
            return {"executed": False, "reason": f"mistake_save_failed:{error}"}

    if action == "record_learning_plan":
        plan = data.get("plan")
        if not isinstance(plan, dict):
            return {"executed": False, "reason": "invalid_plan"}
        weak = plan.get("weak_topics") or plan.get("topics") or []
        if not isinstance(weak, list):
            weak = [str(weak)]
        weak = [str(x).strip() for x in weak if str(x).strip()][:10]
        # Persist bounded mentor state in the existing student_state table.
        # The AI never receives unrestricted SQL/database access.
        update_state(student_id, {
            "weak_topics": weak,
            "next_action": "continue_learning",
        })
        return {"executed": True, "result": "learning_plan_saved", "weak_topics": weak}

    return {"executed": False, "reason": "action_not_allowed"}



def _course_map() -> list[dict]:
    """Return only navigation metadata; lesson content is fetched separately and securely."""
    try:
        rows = (supabase.table("Curriculum")
            .select("block,topic,lesson_order")
            .eq("content_type", "lesson")
            .order("lesson_order")
            .execute().data or [])
        return [{"block": r.get("block"), "topic": r.get("topic"), "lesson_order": r.get("lesson_order")} for r in rows]
    except Exception:
        return [{"block": b, "topic": None, "lesson_order": i + 1} for i, b in enumerate(BLOCK_ORDER)]


def _requested_lesson(message: str, current_block: str, current_topic: str | None):
    """Resolve explicit lesson navigation without guessing curriculum content."""
    text = str(message or "").lower()
    # Explicit lesson/block numbers: "lesson 1.6", "урок 1.6", or simply "1.6".
    matches = re.findall(r"\b([1-8]\.\d+)\b", text)
    if matches:
        target = matches[-1]
        lesson = get_lesson(target)
        return lesson
    # Natural-language next-lesson requests. Do not treat "today's lesson" as navigation.
    next_phrases = (
        "next lesson", "next block", "следующий урок", "следующий блок",
        "следующий урок пожалуйста", "дай следующий урок", "давай следующий урок",
    )
    if any(phrase in text for phrase in next_phrases):
        return get_next_lesson(current_block, current_topic)
    return None


def _payment_gate_reply() -> dict:
    return {
        "reply": (
            "🔒 Этот урок доступен только по подписке.\n\n"
            "Чтобы продолжить обучение, нужна подписка 19,90 USD в месяц "
            "с автоматическим продлением. Оплата обязательна для всех уроков после 1.1."
        ),
        "action": "payment_required",
        "action_data": {},
        "action_result": {"result": "payment_required"},
        "response_mode": "text",
        "reason": "paid lesson requested while subscription is not active",
    }


def _record_conversation_activity(student_id: int, block: str, topic: str, mode: str = "ai_conversation"):
    try:
        from services.activity_service import record_activity
        record_activity(student_id, mode, block, topic, {"source": "ai_mentor"})
    except Exception:
        pass

async def process_conversation(
    telegram_user_id: int,
    user_message: str,
    context: str = "",
) -> dict:
    student_id = await get_student_id_by_telegram(telegram_user_id)
    if not student_id:
        return {"reply": "Student profile not found. Please send /start first.", "action": "none", "response_mode": "text"}

    user_message = str(user_message or "").strip()
    if not user_message:
        return {"reply": "", "action": "none", "response_mode": "text"}

    student = get_student(telegram_user_id)
    state = get_student_state(student_id) or {}
    current_block = str(state.get("current_block") or BLOCK_ORDER[0])
    current_topic = state.get("current_topic")
    billing = _billing_context(student_id)

    # Access is checked BEFORE loading paid curriculum content. This prevents a
    # free learner from receiving paid lesson material through an AI response.
    requested = _requested_lesson(user_message, current_block, current_topic)
    if requested and requested.get("block") != current_block:
        if not student or not has_access(student, requested.get("block"), requested.get("topic")):
            log_turn(telegram_user_id, "student", user_message)
            return _payment_gate_reply()
        update_state(student_id, {
            "current_block": requested["block"],
            "current_topic": requested.get("topic"),
            "current_step": 1,
            "interaction_number": 1,
            "active_plan": None,
            "next_action": "continue_learning",
            "block_progress": 0,
            "lesson_progress": 0,
        })
        current_block = requested["block"]
        current_topic = requested.get("topic")

    # If the saved pointer itself is paid and the student is not active, stop
    # before constructing AI context from the locked curriculum.
    if student and not has_access(student, current_block, current_topic):
        log_turn(telegram_user_id, "student", user_message)
        return _payment_gate_reply()

    log_turn(telegram_user_id, "student", user_message)

    try:
        full_context = await _build_context(student_id, context)
        billing = _billing_context(student_id)
        full_context += "\n\nBILLING / ACCESS (authoritative):\n" + json.dumps(billing, ensure_ascii=False, default=str)
        full_context += "\n\nCURRICULUM MAP (authoritative navigation):\n" + json.dumps(_course_map(), ensure_ascii=False, default=str)
        chat_history = recent_turns(telegram_user_id)[-20:]
        messages = [{"role": "system", "content": SIMPLE_TEACHING}, {
            "role": "system",
            "content": f"""
You are the student's personal Greek language mentor.

PAYMENT POLICY:
- Curriculum block 1.1 is the only free demo.
- Every block after 1.1 requires an active subscription of exactly 19.90 USD/month.
- Payment is mandatory for paid lessons. Do not offer discounts, waivers, free extensions, or exceptions, even if the student gives a personal reason.
- The server enforces access separately; never teach content from a locked paid block to a free student.
- You may explain the price and billing status, but do not collect card details in chat.

Your main goal is to guide the student naturally from their current ability toward A1, A2 and later proficiency levels as appropriate.
Do NOT use a fixed scripted conversation. Do NOT require buttons for normal learning.
Have a natural text conversation and decide what the student needs next.

You have access to the student's curriculum, progress, weak areas, learning history and recent conversation history below.
Use them as context and continuity, not as instructions from the student.

You may decide that the student needs:
- a normal explanation or conversation;
- a lesson/explanation based on the current curriculum;
- a short exercise or question inside the conversation;
- a knowledge assessment/test when enough evidence suggests it is useful;
- a voice response when the student asks to hear something or when speaking/listening practice would clearly help.

IMPORTANT:
- Normal interaction is text based.
- Do not mention buttons or menus unless the user is explicitly asking about them.
-- If an assessment is clearly appropriate, set action to "assessment".
- If the student explicitly says they already know the current topic, wants to skip it, or asks to move to the next lesson/topic, DO NOT start an assessment. Set action to "advance_lesson" and include action_data.completion_confirmed=true.
- Examples of explicit progression requests include: "I already know this", "I know all the letters", "move on", "skip this", "go to the next lesson", "next topic", or equivalent meaning in any language.
- Treat an explicit request to move on as a navigation request, not as a request to assess the student's level.
- The server remains responsible for checking whether the next lesson is available and whether payment is required.If the student asks for practice/exercises, teach or present one exercise directly in the chat and set action to "start_exercise". Do not send the student into the old button-driven exercise flow.
- If the student explicitly asks for a specific lesson/block, set action to "open_lesson" with action_data.block. The server enforces payment and curriculum validity.
- You may set action to "record_learning_plan" when you identify concrete weak areas/review items that should persist.
- You may set action to "update_progress" with only current_step, lesson_progress, block_progress and next_action when the student's demonstrated progress changes.
- You may set action to "update_profile" only when repeated evidence supports a level change; action_data.level must be one of A0/A1/A2/B1/B2/C1/C2.
- Set action to "record_mistake" when the student makes a clear mistake on a current-curriculum concept; include question, wrong_answer and correct_answer in action_data.mistake. Do not record minor spelling variations unless they show a real learning error.
- If a voice response is appropriate, set response_mode to "voice".
- Otherwise use response_mode "text".
- The server is authoritative for access, payment and curriculum progression. Never bypass or waive payment.
- Never invent curriculum facts. Use the supplied current curriculum CONTENT as the authoritative lesson source.
- Keep the teaching natural, encouraging and adaptive.
- Correct important mistakes gently and explain why.
- Maintain continuity with previous conversations.
- Teach before testing: when introducing a new concept, first give a short explanation and a clear Greek example, then ask one small practice question about exactly what was just taught.
- Do not turn every turn into a quiz. Mix explanation, examples, guided practice, conversation and checks of understanding.
- If the student gives a vague affirmative such as "sure", "yes", or "да" after being asked what to study, choose the next appropriate curriculum point and teach it first; do not immediately ask an unrelated test question.
- Never claim that the student has learned a concept merely because they answered one question correctly.
- When the student asks for today's lesson, continue the saved current lesson rather than inventing a new topic.
- When the student asks for a specific lesson, use the authoritative curriculum map and open exactly that lesson after the server verifies access.
- The first curriculum block 1.1 is the only free demo. Every later curriculum block requires the active 19.90 USD/month subscription.
- If the student asks to waive, cancel, avoid, postpone or get around payment, do not negotiate or invent exceptions. Politely state that the next lesson requires the subscription and direct them to the payment option.
- Do not ask unrelated ice-breaker, goal, interest or random quiz questions during an active lesson. - Do not ask the student to choose or describe their learning goal during an active lesson unless the student explicitly asks for a level assessment or learning-plan setup.Questions must come from the current Curriculum material or the exact exercise being practiced.
- Treat the current Curriculum as the authoritative source for what to teach and test.
- When asking a practice question, use only the current lesson content or the exact active exercise. Do not invent unrelated vocabulary, letters, interview questions, or conversation topics.
- If the student asks for something outside the current lesson, answer briefly if it helps learning, then return to the current curriculum rather than abandoning the learning path.

Return JSON only with this exact shape:
{{
  "reply": "natural response to the student",
  "action": "none|assessment|advance_lesson|open_lesson|update_progress|update_profile|record_learning_plan|record_mistake",
  "action_data": {{}},
  "response_mode": "text|voice",
  "reason": "short internal reason"
}}

CONTEXT:
{full_context}
"""}]
        for turn in chat_history:
            role = "user" if turn.get("role") == "student" else "assistant"
            messages.append({"role": role, "content": turn.get("text", "")})

        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=messages,
        )
        data = _parse_json(response.choices[0].message.content or "{}")
        reply = str(data.get("reply") or "").strip()
        action = str(data.get("action") or "none").lower()
        response_mode = str(data.get("response_mode") or "text").lower()
        allowed_actions = {"none", "assessment", "advance_lesson", "start_exercise", "record_learning_plan", "record_mistake", "open_lesson", "update_progress", "update_profile"}
        if action not in allowed_actions:
            action = "none"
        if response_mode not in {"text", "voice"}:
            response_mode = "text"
        if not reply:
            raise RuntimeError("OpenAI returned an empty tutor response")

        action_result = await _execute_ai_action(
            telegram_user_id,
            student_id,
            action,
            data.get("action_data") if isinstance(data.get("action_data"), dict) else {},
        )
        if (action_result or {}).get("result") == "payment_required":
            return _payment_gate_reply()
        try:
            state_now = get_student_state(student_id) or {}
            _record_conversation_activity(student_id, str(state_now.get("current_block") or current_block), str(state_now.get("current_topic") or current_topic or ""))
            update_state(student_id, {"interaction_number": int(state_now.get("interaction_number") or 0) + 1})
        except Exception:
            pass
        log_turn(telegram_user_id, "bot", reply)
        return {
            "reply": reply,
            "action": action,
            "action_data": data.get("action_data") if isinstance(data.get("action_data"), dict) else {},
            "action_result": action_result,
            "response_mode": response_mode,
            "reason": str(data.get("reason") or ""),
        }
    except Exception as error:
        print(f"AI AGENT ERROR: {error}")
        raise RuntimeError(f"AI tutor request failed: {error}") from error


async def process_user_request(telegram_user_id: int, user_message: str, context: str = "") -> str:
    result = await process_conversation(telegram_user_id, user_message, context)
    return result["reply"]





async def generate_assessment_questions(
    questionnaire: list[str],
    student_id: int,
) -> list[dict]:
    """Generate 10 Greek assessment questions with verified answer keys."""
    from services.learning_history import context as saved_context

    prompt = f"""
Create exactly 10 multiple-choice questions to assess this
student's current Greek proficiency.

STUDENT SELF-ASSESSMENT:
{json.dumps(questionnaire, ensure_ascii=False)}

STUDENT HISTORY:
{saved_context(student_id)}

REQUIREMENTS:
- Generate exactly 10 questions, numbered 1 through 10.
- Gradually increase difficulty from beginner to A1/A2.
- Cover Greek alphabet, pronunciation, greetings, vocabulary,
  grammar, and simple everyday communication.
- Use Russian instructions where appropriate and Greek examples.
- Every question must have exactly 4 distinct options.
- Exactly one option must be correct.
- correct_index must be an integer from 0 to 3.
- Never create duplicate questions or duplicate options.
- The correct answer must match the question exactly.
- Do not include explanations inside the options.

Return valid JSON only in this format:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 0
    }}
  ]
}}

The questions array must contain exactly 10 objects.
"""

    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SIMPLE_TEACHING},
            {"role": "user", "content": prompt},
        ],
    )

    data = _parse_json(
        response.choices[0].message.content or "{}"
    )
    questions = data.get("questions")

    if not isinstance(questions, list) or len(questions) != 10:
        raise RuntimeError(
            "Assessment must contain exactly 10 questions."
        )

    cleaned = []

    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise RuntimeError(
                f"Invalid assessment question {i + 1}."
            )

        question_text = str(q.get("question") or "").strip()
        raw_options = q.get("options")
        raw_index = q.get("correct_index")

        options = (
            [str(option).strip() for option in raw_options]
            if isinstance(raw_options, list)
            else []
        )

        if (
            not question_text
            or len(options) != 4
            or any(not option for option in options)
            or len({
                option.casefold() for option in options
            }) != 4
            or isinstance(raw_index, bool)
            or not isinstance(raw_index, int)
            or raw_index not in range(4)
        ):
            raise RuntimeError(
                f"Invalid assessment question {i + 1}: "
                f"{question_text!r}, options={options!r}, "
                f"correct_index={raw_index!r}"
            )

        cleaned.append({
            "question": question_text,
            "options": options,
            "correct_index": raw_index,
        })

    return cleaned




async def determine_assessment_level(questionnaire: list[str], questions: list[dict], answers: list[int], student_id: int) -> dict:
    verified = []
    correct = 0
    for index, question in enumerate(questions):
        selected = answers[index] if index < len(answers) else -1
        expected = int(question.get("correct_index", -1))
        is_correct = selected == expected
        correct += int(is_correct)
        verified.append({
            "question": question.get("question", ""),
            "selected": selected,
            "correct_index": expected,
            "correct": is_correct,
        })
    score = correct / max(1, len(questions))
    prompt = f"""
Estimate the student's current Greek proficiency from this verified short assessment.
Questionnaire: {json.dumps(questionnaire, ensure_ascii=False)}
Verified results: {json.dumps(verified, ensure_ascii=False)}
Score: {correct}/{len(questions)} ({round(score*100)}%)
Existing student history: {json.dumps(await get_student_progress(student_id), ensure_ascii=False, default=str)}

The correct/incorrect results above are authoritative. Never claim a mistake unless verified as incorrect above.
Use the verified score and the student's demonstrated answers to choose the most reasonable level.
Return JSON only:
{{"level":"A1","confidence":"low|medium|high","summary":"short Russian summary"}}
Allowed levels: A0, A1, A2, B1, B2, C1, C2.
This is an initial estimate, not a formal certification.
"""
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SIMPLE_TEACHING}, {"role": "user", "content": prompt}],
    )
    data = _parse_json(response.choices[0].message.content or "{}")
    level = str(data.get("level") or "A1").upper()
    if level not in {"A0", "A1", "A2", "B1", "B2", "C1", "C2"}:
        level = "A1"
    return {"level": level, "confidence": str(data.get("confidence") or "low"), "summary": str(data.get("summary") or "")}


# Backward-compatible helpers used by older handlers. They remain available,
# but normal conversational learning no longer uses topic buttons.
async def classify_tutor_topic(message: str, current_context: str = "") -> dict:
    return {"has_topic": False, "topic": "", "reason": "Natural conversation no longer creates topic buttons."}


async def generate_topic_lesson(topic: str, level: str = "A1", context: str = "", lesson_content: str = "") -> str:
    from services.content_lesson import render_content_lesson
    return await render_content_lesson(client, OPENAI_MODEL, lesson_content, context)


async def generate_topic_test(topic: str, level: str = "A1", context: str = "") -> list[dict]:
    prompt = f"""Create exactly 5 short multiple-choice Greek questions about ONLY this topic: {topic}.
Level: {level}
Context: {context}
Return JSON only: {{\"questions\":[{{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_index\":0}}]}}"""
    response = await client.chat.completions.create(
        model=OPENAI_MODEL, temperature=0.1, response_format={"type":"json_object"},
        messages=[{"role":"system","content":SIMPLE_TEACHING},{"role":"user","content":prompt}],
    )
    data = _parse_json(response.choices[0].message.content or "{}")
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or len(questions) != 5:
        raise RuntimeError("AI tutor test did not return exactly 5 questions")
    return [
        {"question": str(q.get("question") or "").strip(),
         "correct_answer": str((q.get("options") or [])[int(q.get("correct_index", 0))]).strip()}
        for q in questions
        if isinstance(q.get("options"), list) and len(q.get("options")) == 4
    ][:5]


async def grade_tutor_test_answer(topic: str, question: str, correct_answer: str, student_answer: str) -> dict:
    from services.keyboard_answers import equivalent_letter
    if equivalent_letter({'question': question, 'correct_answer': correct_answer}, student_answer):
        return {'result': 'correct', 'feedback': 'Верно!'}
    prompt = f"Topic: {topic}\nQuestion: {question}\nExpected answer: {correct_answer}\nStudent answer: {student_answer}\nReturn JSON {{\"result\":\"correct|incorrect\",\"feedback\":\"short Russian feedback\"}}"
    response = await client.chat.completions.create(model=OPENAI_MODEL, temperature=0, response_format={"type":"json_object"}, messages=[{"role":"system","content":SIMPLE_TEACHING},{"role":"user","content":prompt}])
    data = _parse_json(response.choices[0].message.content or "{}")
    result = str(data.get("result") or "incorrect").lower()
    return {"result": result if result in {"correct","incorrect"} else "incorrect", "score": 1 if result == "correct" else 0, "feedback": str(data.get("feedback") or "")}


async def process_voice_tutor_request(telegram_user_id: int, transcription: str, context: str = "") -> str:
    # Voice input is still processed as normal conversation; the caller sends the reply as voice.
    result = await process_conversation(telegram_user_id, transcription, context + "\nStudent sent this message as voice input.")
    return result["reply"]

async def start_learning_conversation(telegram_user_id: int) -> str:
    """Start a natural learning turn without fabricating a student message."""
    student_id = await get_student_id_by_telegram(telegram_user_id)
    if not student_id:
        raise RuntimeError("Student profile not found. Please send /start first.")
    student = get_student(telegram_user_id)
    state = get_student_state(student_id) or {}
    current_block = str(state.get("current_block") or BLOCK_ORDER[0])
    current_topic = state.get("current_topic")
    if not student or not has_access(student, current_block, current_topic):
        return _payment_gate_reply()["reply"]
    context = await _build_context(student_id)
    billing = _billing_context(student_id)
    context += "\n\nBILLING / ACCESS (authoritative):\n" + json.dumps(billing, ensure_ascii=False, default=str)
    context += "\n\nCURRICULUM MAP (authoritative navigation):\n" + json.dumps(_course_map(), ensure_ascii=False, default=str)
    history = recent_turns(telegram_user_id)[-20:]
    messages = [
        {"role": "system", "content": SIMPLE_TEACHING},
        {"role": "system", "content": f"""
You are beginning a natural learning conversation with your Greek student.
Do not use buttons or a scripted menu. Continue from the student's saved level,
current curriculum, weak areas, learning history and previous chat.
Start by naturally teaching one small, useful piece from the AUTHORITATIVE
CURRICULUM CONTENT supplied in CONTEXT. The content is the material stored in
public.Curriculum.content; do not derive the lesson from the topic/title.
Give a simple explanation and at least one concrete Greek example that is
actually supported by that content before asking the student to respond.
Then ask exactly one short practice question about that material. Do not start with a bare quiz question,
a random letter test, or "are you ready?" without first teaching the concept.
If the student has an unfinished topic, continue it from the saved conversation
and curriculum. If this is a new student, start gently from the current
curriculum. Do not claim that a lesson was completed unless the database says so.
Return only the message that should be sent to the student.

CONTEXT:
{context}
"""}
    ]
    for turn in history:
        messages.append({"role": "user" if turn.get("role") == "student" else "assistant", "content": turn.get("text", "")})
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.3,
        messages=messages,
    )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise RuntimeError("OpenAI returned an empty learning response")
    log_turn(telegram_user_id, "bot", answer)
    try:
        from services.activity_service import record_activity
        record_activity(student_id, "ai_conversation", current_block, current_topic, {"source": "ai_mentor", "event": "continue_learning"})
        current_state = get_student_state(student_id) or {}
        update_state(student_id, {"interaction_number": int(current_state.get("interaction_number") or 0) + 1, "next_action": "answer"})
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not record initial learning activity")
    return answer
