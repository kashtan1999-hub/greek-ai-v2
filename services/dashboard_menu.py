import asyncio
import logging
from services.russian_ui import russian_text
from aiogram.types import BufferedInputFile
from services.progress_service import get_student_progress, format_progress
from services.dashboard_image import render_dashboard

async def send_dashboard(message, student_id, keyboard, caption="🎮 Греческий язык\n\nВыберите действие:"):
    announcement = "🇬🇷 Скоро: курс подготовки к получению гражданства Греции, включая подготовку к собеседованию на греческом языке."
    is_main = any(button.callback_data in {"game_continue", "start_lesson", "continue_learning"} for row in getattr(keyboard, "inline_keyboard", []) for button in row)
    if is_main:
        caption += "\n\n" + announcement
    progress = await get_student_progress(student_id)
    try:
        progress = dict(progress)
        progress["state"] = dict(progress["state"])
        progress["state"]["current_topic"] = await russian_text(str(progress["state"].get("current_topic") or "Не начато"))
        for field in ("date_label",):
            if progress.get(field):
                progress[field] = await russian_text(str(progress[field]))
        days = {"Mon":"Пн", "Tue":"Вт", "Wed":"Ср", "Thu":"Чт", "Fri":"Пт", "Sat":"Сб", "Sun":"Вс"}
        progress["daily_activity"] = [dict(row, label=days.get(row["label"], row["label"])) for row in progress.get("daily_activity", [])]
        for row in progress.get('recent_history', []):
            row['topic'] = await russian_text(str(row.get('topic') or ''))
        png = await asyncio.to_thread(render_dashboard, progress)
        return await message.answer_photo(BufferedInputFile(png, filename="progress.png"), caption=caption, reply_markup=keyboard)
    except Exception:
        logging.exception("Dashboard image failed; using text")
        return await message.answer(format_progress(progress) + ("\n\n" + announcement if is_main else ""), reply_markup=keyboard)
