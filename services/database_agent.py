from services.supabase_client import supabase
from services.student_service import normalize_block



async def get_student_progress(
    student_id: int
) -> dict:
    """
    Get student progress information.
    """

    try:

        state = (
            supabase
            .table("student_state")
            .select("*")
            .eq(
                "student_id",
                student_id
            )
            .limit(1)
            .execute()
        )


        attempts = (
            supabase
            .table("attempts")
            .select("score")
            .eq(
                "student_id",
                student_id
            )
            .execute()
        )


        scores = [
            float(item["score"])
            for item in (attempts.data or [])
            if item.get("score") is not None
        ]


        accuracy = 0


        if scores:

            accuracy = round(
                sum(scores)
                /
                len(scores)
                *
                100
            )


        data = (
            state.data[0]
            if state.data
            else {}
        )


        return {

            "level":
                data.get(
                    "level",
                    "A1"
                ),

            "current_block":
                data.get(
                    "current_block",
                    "1.1"
                ),

            "current_topic":
                data.get(
                    "current_topic",
                    "Introduction"
                ),

            "accuracy":
                accuracy,

            "total_attempts":
                len(scores)

        }



    except Exception as error:

        print(
            f"GET PROGRESS ERROR: {error}"
        )

        return {}





async def get_weak_topics(
    student_id: int
) -> list[str]:
    """
    Get unresolved learning mistakes.
    """

    try:

        response = (

            supabase
            .table("learning_errors")
            .select("topic")
            .eq(
                "student_id",
                student_id
            )
            .eq(
                "resolved",
                False
            )
            .execute()

        )


        topics = [

            item["topic"]

            for item in (response.data or [])

        ]


        return list(
            set(topics)
        )


    except Exception as error:

        print(
            f"GET WEAK TOPICS ERROR: {error}"
        )

        return []






async def get_student_id_by_telegram(
    telegram_user_id: int
):
    """
    Convert Telegram user ID
    into Students table ID.
    """

    try:

        response = (

            supabase
            .table("Students")
            .select("id")
            .eq(
                "telegram_user_id",
                telegram_user_id
            )
            .limit(1)
            .execute()

        )


        if response.data:

            return response.data[0]["id"]


        print(
            "STUDENT NOT FOUND:",
            telegram_user_id
        )


        return None



    except Exception as error:

        print(
            f"GET STUDENT ID ERROR: {error}"
        )

        return None






async def get_current_lesson(student_id: int):
    from services.curriculum_service import get_lesson, require_content
    response = supabase.table('student_state').select('current_block,current_topic').eq('student_id',student_id).limit(1).execute()
    if not response.data: return {}
    block = normalize_block(response.data[0].get('current_block'))
    lesson = get_lesson(block)
    if lesson: require_content(lesson)
    return lesson or {}
