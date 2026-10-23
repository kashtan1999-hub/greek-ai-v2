"""Per-process conversational mode state for Telegram interactions.

Supabase remains the source of truth for learning/progress. This small in-memory
store only keeps transient Telegram conversation mode (tutor chat/test or
speaking practice) so text/voice messages are routed to the correct handler.
"""

_sessions: dict[int, dict] = {}


def set_session(user_id: int, mode: str, **values) -> None:
    _sessions[user_id] = {"mode": mode, **values}


def get_session(user_id: int) -> dict:
    return _sessions.get(user_id, {})


def clear_session(user_id: int) -> None:
    _sessions.pop(user_id, None)


def is_mode(user_id: int, mode: str) -> bool:
    return _sessions.get(user_id, {}).get("mode") == mode
