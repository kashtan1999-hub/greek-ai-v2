"""Durable per-user conversation history with an in-memory fallback.

The Supabase table is created by sql/conversation_history.sql. If the table is
not available yet, the bot keeps a small in-process fallback so conversation
still works while the migration is being applied.
"""
from collections import defaultdict, deque
from typing import Literal
from services.supabase_client import supabase

MAX_TURNS = 40
Role = Literal["student", "bot"]
_log: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_TURNS))


def _student_id(telegram_user_id: int):
    try:
        rows = supabase.table("Students").select("id").eq("telegram_user_id", telegram_user_id).limit(1).execute().data or []
        return rows[0]["id"] if rows else None
    except Exception as error:
        print("CONVERSATION STUDENT LOOKUP ERROR:", repr(error))
        return None


def log_turn(telegram_user_id: int, role: Role, text: str) -> None:
    if not text:
        return
    item = {"role": role, "text": str(text)}
    _log[telegram_user_id].append(item)
    student_id = _student_id(telegram_user_id)
    if not student_id:
        return
    try:
        supabase.table("conversation_history").insert({
            "student_id": student_id,
            "role": role,
            "content": str(text),
        }).execute()
    except Exception as error:
        # Keep the bot functional if the migration has not been run yet.
        print("CONVERSATION HISTORY SAVE ERROR:", repr(error))


def recent_turns(telegram_user_id: int) -> list[dict]:
    student_id = _student_id(telegram_user_id)
    if student_id:
        try:
            rows = supabase.table("conversation_history").select("role,content,created_at").eq("student_id", student_id).order("created_at", desc=True).limit(MAX_TURNS).execute().data or []
            rows.reverse()
            if rows:
                return [{"role": row.get("role"), "text": row.get("content", "")} for row in rows]
        except Exception as error:
            print("CONVERSATION HISTORY READ ERROR:", repr(error))
    return list(_log.get(telegram_user_id, []))


def format_recent_turns(telegram_user_id: int) -> str:
    turns = recent_turns(telegram_user_id)
    if not turns:
        return "(no recent messages)"
    lines = []
    for turn in turns:
        speaker = "Student" if turn["role"] == "student" else "Tutor"
        lines.append(f"{speaker}: {turn['text']}")
    return "\n".join(lines)
