from services.teaching_policy import SIMPLE_TEACHING
import os
import tempfile
from pathlib import Path

from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


async def transcribe_greek_voice(
    bot,
    voice,
    language: str | None = "el",
) -> str:
    file_info = await bot.get_file(voice.file_id)
    fd, audio_path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)

    try:
        await bot.download_file(file_info.file_path, audio_path)
        with open(audio_path, "rb") as audio:
            kwargs = {
                "model": "whisper-1",
                "file": audio,
            }
            if language:
                kwargs["language"] = language

            transcription = await client.audio.transcriptions.create(
                **kwargs
            )

        text = (getattr(transcription, "text", None) or "").strip()
        if not text:
            raise RuntimeError("Whisper returned an empty transcription")
        return text
    finally:
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception:
            pass


async def analyze_greek_speech(
    bot,
    voice,
    block_context=None,
    transcription: str | None = None,
):
    text = transcription or await transcribe_greek_voice(bot, voice)
    context = block_context or "No current lesson context supplied."

    prompt = f"""
You are a supportive Greek speaking-practice tutor for an A1 beginner.

Current learning context:
{context}

Student's speech transcription from Whisper:
{text}

Important limitation:
The text above is a transcription, not a direct acoustic measurement of the student's
audio. Do NOT claim that you detected an exact pronunciation error from the transcript
alone. Whisper can also make spelling or accent mistakes.

Speaking-practice grading rules:
- Be supportive and NOT overly strict.
- If the transcription clearly represents the expected Greek word/phrase for the
  current lesson, treat it as acceptable even if accents, spelling, or transcription
  details differ.
- Do not penalize harmless accent/diacritic differences.
- Do not treat a likely Whisper spelling error as proof that the student pronounced
  the word incorrectly.
- Only point out a pronunciation or language problem when it is reasonably supported
  by the transcription and current context.
- If the student's intended Greek is unclear, say that the transcription is unclear
  rather than inventing a pronunciation problem.
- Focus on the current learning block/topic.
- Keep the explanation simple for A1.
- Show the corrected Greek form in Greek script when useful.
- Give one short, practical improvement tip.

Return a short, friendly Russian explanation containing:
1. What was understood.
2. Whether the attempt is acceptable / needs practice.
3. Correct Greek form when useful.
4. One simple improvement tip.
"""

    response = await client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[{"role": "system", "content": SIMPLE_TEACHING},
            {
                "role": "system", "name": "teacher",
                "content": (
                    "You are a supportive Greek speaking tutor. "
                    "Do not over-correct beginners and do not invent "
                    "pronunciation errors from text alone."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    analysis = (response.choices[0].message.content or "").strip()
    if not analysis:
        raise RuntimeError("OpenAI returned empty speaking analysis")

    return {
        "transcription": text,
        "analysis": analysis,
    }
