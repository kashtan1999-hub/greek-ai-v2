from services.dashboard_menu import send_dashboard
import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from keyboards.game_menu import game_main_menu
from services.supabase_client import supabase


router = Router()

logger = logging.getLogger(__name__)


DEFAULT_BLOCK = "1.1"

DEFAULT_TOPIC = "Greek Alphabet Recognition"

DEFAULT_LEVEL = "A1"





@router.message(CommandStart())
async def start_command(
    message: Message
):

    user = message.from_user


    if user is None:
        return



    if message.chat.type != "private":

        await message.answer(
            "Please open this bot in a private chat and send /start."
        )

        return



    current_time = (
        datetime
        .now(timezone.utc)
        .isoformat()
    )



    try:


        existing_student = (

            supabase
            .table("Students")
            .select("id")
            .eq(
                "telegram_user_id",
                user.id
            )
            .limit(1)
            .execute()

        )



        profile = {

            "chat_id":
                message.chat.id,

            "first_name":
                user.first_name or "Student",

            "username":
                user.username,

            "language":
                user.language_code or "en"

        }




        is_new_student = not existing_student.data




        if is_new_student:



            new_student = (

                supabase
                .table("Students")
                .insert(
                    {

                        **profile,


                        "telegram_user_id":
                            user.id,


                        "created_at":
                            current_time,


                        "subscription_status":
                            "free"

                    }
                )
                .execute()

            )


            student_id = (
                new_student
                .data[0]["id"]
            )



        else:


            student_id = (

                existing_student
                .data[0]["id"]

            )


            (
                supabase
                .table("Students")
                .update(profile)
                .eq(
                    "id",
                    student_id
                )
                .execute()
            )





        state_response = (

            supabase
            .table("student_state")
            .select(
                """
                level,
                current_block,
                current_topic,
                current_step
                """
            )
            .eq(
                "student_id",
                student_id
            )
            .limit(1)
            .execute()

        )





        if state_response.data:



            state = state_response.data[0]



            (
                supabase
                .table("student_state")
                .update(
                    {

                        "last_activity_at":
                            current_time,


                        "updated_at":
                            current_time

                    }
                )
                .eq(
                    "student_id",
                    student_id
                )
                .execute()
            )





        else:



            state = {


                "level":
                    DEFAULT_LEVEL,


                "current_block":
                    DEFAULT_BLOCK,


                "current_topic":
                    DEFAULT_TOPIC,


                "current_step":
                    1


            }



            (
                supabase
                .table("student_state")
                .insert(
                    {

                        "student_id":
                            student_id,


                        **state,


                        "weak_topics":
                            [],


                        "active_plan":
                            None,


                        "next_action":
                            "start_block_1.1",


                        "last_activity_at":
                            current_time,


                        "updated_at":
                            current_time

                    }
                )
                .execute()
            )





        greeting = (


            f"Welcome, {profile['first_name']}! 🇬🇷\n\n"
            "I am your personal Greek language tutor."

            if is_new_student


            else


            f"Welcome back, {profile['first_name']}! 🇬🇷\n\n"
            "Your learning progress is saved."

        )





        progress = (


            f"📚 Level: {state.get('level') or DEFAULT_LEVEL}\n"


            f"📖 Block: {state.get('current_block') or DEFAULT_BLOCK}\n"


            f"📝 Topic: {state.get('current_topic') or DEFAULT_TOPIC}\n"


            f"👣 Step: {state.get('current_step') or 1}"


        )





        await send_dashboard(message, student_id, game_main_menu(), greeting + "\n\nChoose your next action:")
        from handlers.profile import welcome
        await welcome(message, student_id, is_new_student=is_new_student)





    except Exception as error:


        logger.exception(
            "Failed to handle /start",
            exc_info=error
        )


        await message.answer(
            "Sorry, we could not load your profile. Please try again."
        )