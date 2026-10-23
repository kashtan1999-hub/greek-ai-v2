import os
import uuid
from pathlib import Path

from openai import AsyncOpenAI
from services.russian_ui import russian_text

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def generate_voice(text: str) -> str:
    """Generate Telegram-friendly voice audio using OpenAI TTS."""
    if not text or not text.strip():
        raise ValueError("Cannot generate voice from empty text.")

    text = await russian_text(text)

    path = Path(f"ai_response_{uuid.uuid4().hex}.ogg")
    try:
        speed = float(os.getenv("OPENAI_TTS_SPEED", "0.85"))
    except ValueError:
        speed = 0.85
    speed = max(0.5, min(speed, 1.0))

    response = await client.audio.speech.create(
        model=os.getenv("OPENAI_TTS_MODEL", "tts-1"),
        voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
        input=text.strip(),
        response_format="opus",
        speed=speed,
    )
    response.stream_to_file(str(path))
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("OpenAI TTS returned an empty audio file.")
    return str(path)
