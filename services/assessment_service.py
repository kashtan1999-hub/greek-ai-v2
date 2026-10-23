from services.supabase_client import supabase


PASS_SCORE = 80



def calculate_score(
    total_questions: int,
    correct_answers: int
) -> int:

    if total_questions <= 0:
        return 0

    percentage = (
        correct_answers / total_questions
    ) * 100

    return round(percentage)



def check_assessment_result(
    score: int
) -> dict:

    if score >= PASS_SCORE:

        return {
            "passed": True,
            "message": (
                "🎉 Congratulations!\n\n"
                "You passed this assessment.\n"
                "Review later to check retention."
            )
        }


    return {
        "passed": False,
        "message": (
            "💪 Keep practicing.\n\n"
            "Review this lesson and try again "
            "to unlock the next block."
        )
    }



async def save_attempt(
    student_id: int,
    exercise_id: int,
    answer: str,
    correct: bool,
    score: int
):

    try:

        response = (
            supabase
            .table("attempts")
            .insert(
                {
                    "student_id": student_id,
                    "exercise_id": exercise_id,
                    "answer": answer,
                    "correct": correct,
                    "score": score,
                }
            )
            .execute()
        )

        return response.data


    except Exception as error:

        print(
            f"SAVE ATTEMPT ERROR: {error}"
        )

        return None



async def unlock_next_block(
    student_id: int,
    current_block: str
):

    """
    Unlock next curriculum block
    """

    try:

        from services.student_service import get_student_state
        from services.curriculum_service import get_next_lesson
        state = get_student_state(student_id) or {}
        current = state.get('current_block')
        topic = state.get('current_topic')
        path = supabase.table('learning_paths').select('retained').eq('student_id',student_id).eq('block',current).eq('topic',topic).limit(1).execute().data or []
        if not path or not path[0].get('retained'):
            return None
        lesson = get_next_lesson(current, topic)
        if not lesson:
            return None
        next_block = lesson['block']

        response = (
            supabase
            .table("student_state")
            .update(
                {
                    "current_block": next_block,
                    "current_topic": lesson["topic"],
                    "current_step": 1,
                    "next_action": (
                        f"start_block_{next_block}"
                    ),
                }
            )
            .eq(
                "student_id",
                student_id
            )
            .execute()
        )


        return response.data


    except Exception as error:

        print(
            f"UNLOCK BLOCK ERROR: {error}"
        )

        return None