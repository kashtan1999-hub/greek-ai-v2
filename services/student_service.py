from datetime import datetime, timezone
from typing import Any

from services.supabase_client import supabase



# Complete learning sequence

from services.course_sequence import BLOCK_ORDER


TOTAL_BLOCKS = len(BLOCK_ORDER)


MAX_TOPIC_INTERACTIONS = 20





def utc_now():

    return datetime.now(
        timezone.utc
    ).isoformat()







def normalize_block(value: Any):
    raw = str(value or BLOCK_ORDER[0]).strip()
    if raw in BLOCK_ORDER:
        return raw
    raise ValueError("Старый блок курса. Используй /course для выбора нового урока. История сохранится.")


def get_student(
    telegram_user_id: int
):


    response = (

        supabase
        .table("Students")
        .select(
            """
            id,
            first_name,
            subscription_status,
            trial_expires_at
            """
        )
        .eq(
            "telegram_user_id",
            telegram_user_id
        )
        .limit(1)
        .execute()

    )



    return (

        response.data[0]

        if response.data

        else None

    )









def get_student_state(
    student_id: int
):


    response = (

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



    return (

        response.data[0]

        if response.data

        else None

    )









def update_state(
    student_id: int,
    values: dict
):


    payload = {

        **values,

        "updated_at":
            utc_now(),

        "last_activity_at":
            utc_now()

    }



    (

        supabase
        .table("student_state")
        .update(payload)
        .eq(
            "student_id",
            student_id
        )
        .execute()

    )









def get_interaction_number(
    state: dict
):

    return int(

        state.get(
            "interaction_number",
            1
        )

    )









def increase_interaction(
    student_id: int,
    state: dict
):


    current = get_interaction_number(
        state
    )


    new_value = current + 1



    update_state(

        student_id,

        {

            "interaction_number":
                new_value,


            "next_action":
                "continue_learning"

        }

    )


    return new_value









def topic_completed(
    state: dict
):


    return (

        get_interaction_number(
            state
        )

        >=

        MAX_TOPIC_INTERACTIONS

    )









def reset_topic_interaction(
    student_id: int
):


    update_state(

        student_id,

        {

            "interaction_number":
                1,


            "current_step":
                1

        }

    )









def next_block(
    current_block: str
):


    block = normalize_block(
        current_block
    )


    index = BLOCK_ORDER.index(
        block
    )



    if index + 1 >= len(BLOCK_ORDER):

        return None



    return BLOCK_ORDER[index + 1]









def completed_blocks(
    current_block: str
):


    block = normalize_block(
        current_block
    )


    return BLOCK_ORDER.index(
        block
    )









def progress_percent(
    current_block: str
):


    completed = completed_blocks(
        current_block
    )


    return round(

        (

            completed /

            TOTAL_BLOCKS

        )

        *

        100

    )









def move_to_next_lesson(
    student_id: int,
    next_block: str,
    next_topic: str
):


    update_state(

        student_id,

        {


            "current_block":

                normalize_block(
                    next_block
                ),



            "current_topic":

                next_topic,



            "interaction_number":

                1,



            "current_step":

                1,



            "active_plan":

                None,



            "next_action":

                "continue_learning"

        }

    )









def move_to_next_topic(
    student_id: int,
    next_topic: str
):


    update_state(

        student_id,

        {

            "current_topic":

                next_topic,


            "interaction_number":

                1,


            "current_step":

                1,


            "active_plan":

                None,


            "next_action":

                "continue_learning"

        }

    )