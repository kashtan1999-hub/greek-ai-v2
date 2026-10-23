import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from services.russian_ui import RussianUIMiddleware

from handlers.profile import router as profile_router
from handlers.start import router as start_router
from handlers.game_menu import router as game_menu_router
from handlers.menu import router as menu_router
from handlers.tutor import router as tutor_router
from handlers.learning import router as learning_router
from handlers.ai_agent import router as ai_agent_router
from handlers.assessment import router as assessment_router
from handlers.voice import router as voice_router
from handlers.voice_lesson import router as voice_lesson_router


load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)


if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN .env file mein missing hai."
    )



async def main():

    logging.basicConfig(
        level=logging.INFO
    )


    bot = Bot(
        token=TELEGRAM_BOT_TOKEN
    )


    bot.session.middleware(RussianUIMiddleware())

    logging.info('BOT BUILD: PROGRESSION_V4 — staged lessons, resumable quizzes, separate retention reviews')
    dispatcher = Dispatcher()
    from services.loading import LoadingMiddleware
    dispatcher.callback_query.outer_middleware(LoadingMiddleware())


    dispatcher.include_router(profile_router)

    # Start / User registration
    dispatcher.include_router(
        start_router
    )


    # Dashboard navigation
    dispatcher.include_router(
        game_menu_router
    )


    # Remaining menu options
    dispatcher.include_router(
        menu_router
    )


    # AI Tutor
    dispatcher.include_router(
        tutor_router
    )


    # Learning + Exercises
    dispatcher.include_router(
        learning_router
    )


    # AI commands (/ai)
    dispatcher.include_router(
        ai_agent_router
    )

    # Knowledge level assessment
    dispatcher.include_router(
        assessment_router
    )


    # Voice lessons and pronunciation analysis
    dispatcher.include_router(
        voice_router
    )

    # AI voice lessons
    dispatcher.include_router(
        voice_lesson_router
    )



    from services.payment_server import start_payment_server
    payment_runner = None
    try:
        payment_runner = await start_payment_server()

        await bot.delete_webhook(
            drop_pending_updates=True
        )


        print(
            "TELEGRAM BOT IS RUNNING"
        )


        await dispatcher.start_polling(
            bot
        )


    finally:
        if payment_runner:
            await payment_runner.cleanup()
        await bot.session.close()



if __name__ == "__main__":
    asyncio.run(main())