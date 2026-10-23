from services.supabase_client import supabase
from services.student_service import utc_now


def save_voice_practice(
    student_id: int,
    block: str,
    topic: str,
    transcription: str,
    feedback: str,
):
    result = (
        supabase.table("voice_practice_attempts")
        .insert(
            {
                "student_id": student_id,
                "block": block,
                "topic": topic,
                "transcription": transcription,
                "feedback": feedback,
                "created_at": utc_now(),
            }
        )
        .execute()
    )
    if not result.data:
        raise RuntimeError("Voice practice was not saved to Supabase.")
    return result.data[0]
