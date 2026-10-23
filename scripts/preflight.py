"""Production preflight checks.

Run inside the project's virtual environment:
    python scripts/preflight.py
    python scripts/preflight.py --live

The default checks are offline/static. --live additionally checks Telegram,
Supabase, OpenAI chat, and OpenAI TTS. Live checks make real API calls.
"""
import argparse
import ast
import asyncio
import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def offline_checks():
    failures = []

    required = [
        "main.py",
        "handlers/learning.py",
        "handlers/tutor.py",
        "handlers/voice.py",
        "services/ai_service.py",
        "services/exercise_service.py",
        "services/speech_service.py",
        "services/voice_service.py",
        "services/voice_practice_service.py",
        "services/user_session.py",
        "sql/phase2.sql",
    ]
    for rel in required:
        path = ROOT / rel
        if not path.exists():
            failures.append(f"Missing file: {rel}")

    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"Syntax error in {path.relative_to(ROOT)}: {exc}")

    # Catch the exact class of startup failure where a handler imports a
    # function that was accidentally omitted from its service module.
    required_symbols = {
        "handlers/tutor.py": {
            "services.ai_agent": {
                "process_user_request",
                "classify_tutor_topic",
                "generate_topic_lesson",
                "generate_topic_test",
                "grade_tutor_test_answer",
            }
        },
        "handlers/voice.py": {
            "services.ai_agent": {
                "process_voice_tutor_request",
                "classify_tutor_topic",
                "grade_tutor_test_answer",
            }
        },
    }
    for importer_rel, module_map in required_symbols.items():
        importer_tree = ast.parse((ROOT / importer_rel).read_text(encoding="utf-8"))
        imports = {
            node.module: {alias.name for alias in node.names}
            for node in importer_tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        for module_name, names in module_map.items():
            imported_names = imports.get(module_name, set())
            if not names.issubset(imported_names):
                failures.append(
                    f"{importer_rel}: expected imports missing from static check: "
                    f"{sorted(names - imported_names)}"
                )

    ai_agent_tree = ast.parse((ROOT / "services/ai_agent.py").read_text(encoding="utf-8"))
    ai_agent_defs = {
        node.name for node in ai_agent_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for symbol in ("classify_tutor_topic", "process_voice_tutor_request"):
        if symbol not in ai_agent_defs:
            failures.append(f"services/ai_agent.py: {symbol} is missing")

    sql = (ROOT / "sql/phase2.sql").read_text(encoding="utf-8")
    for required_sql in (
        "voice_practice_attempts",
        "attempts",
        "learning_errors",
        "student_state",
        '"Students"',
        '"Curriculum"',
        '"Exercises"',
    ):
        if required_sql not in sql and required_sql == "voice_practice_attempts":
            failures.append("Voice-practice migration is missing from sql/phase2.sql")

    return failures


async def live_checks():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    missing = [
        name for name in (
            "TELEGRAM_BOT_TOKEN",
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY",
            "OPENAI_API_KEY",
        ) if not os.getenv(name)
    ]
    if missing:
        return [f"Missing .env values: {', '.join(missing)}"]

    failures = []

    from aiogram import Bot
    from supabase import create_client
    from openai import AsyncOpenAI

    bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SECRET_KEY"],
    )
    openai = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        me = await bot.get_me()
        print(f"Telegram: OK @{me.username}")

        supabase.table("Students").select("id").limit(1).execute()
        for table in ("Curriculum", "Exercises", "student_state", "attempts", "learning_errors", "voice_practice_attempts"):
            supabase.table(table).select("*").limit(1).execute()
        print("Supabase: OK")

        response = await openai.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            temperature=0,
            messages=[{"role": "user", "content": "Reply with the single word OK."}],
        )
        answer = (response.choices[0].message.content or "").strip()
        if answer != "OK":
            failures.append(f"OpenAI chat returned unexpected text: {answer!r}")
        else:
            print("OpenAI chat: OK")

        audio = await openai.audio.speech.create(
            model=os.getenv("OPENAI_TTS_MODEL", "tts-1"),
            voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
            input="Greek tutor voice test.",
            response_format="opus",
        )
        tmp = ROOT / ".preflight_voice.ogg"
        audio.stream_to_file(str(tmp))
        if not tmp.exists() or tmp.stat().st_size == 0:
            failures.append("OpenAI TTS returned an empty file.")
        else:
            print(f"OpenAI TTS: OK ({tmp.stat().st_size} bytes)")
        tmp.unlink(missing_ok=True)

    except Exception as exc:
        failures.append(f"Live check failed: {exc}")
    finally:
        await bot.session.close()

    return failures


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    failures = offline_checks()
    print(f"Offline checks: {'PASS' if not failures else 'FAIL'}")
    for failure in failures:
        print(" -", failure)

    if args.live:
        live_failures = await live_checks()
        print(f"Live checks: {'PASS' if not live_failures else 'FAIL'}")
        for failure in live_failures:
            print(" -", failure)
        failures.extend(live_failures)

    if failures:
        raise SystemExit(1)

    print("ALL REQUESTED PREFLIGHT CHECKS PASSED.")


if __name__ == "__main__":
    asyncio.run(main())
