from services.teaching_policy import SIMPLE_TEACHING
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI


load_dotenv()


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-4.1-mini"
)


client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)



async def explain_lesson(
    topic: str,
    grammar: str,
    vocabulary: str,
    level: str = "A1"
) -> str:
    """
    Generate AI lesson explanation.
    """

    try:

        prompt = f"""
You are a Greek language tutor.

Student level:
{level}

Topic:
{topic}

Grammar:
{grammar}

Vocabulary:
{vocabulary}


Create a beginner-friendly Greek lesson.

Rules:
- Explain everything in simple Russian.
- Include Greek examples.
- Include Russian translations.
- Include pronunciation when helpful.
- Keep it suitable for A1 beginners.
- Avoid difficult grammar explanations.
"""


        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.5,
            messages=[{"role": "system", "content": SIMPLE_TEACHING},
                {
                    "role": "system", "name": "teacher",
                    "content": (
                        "You are an Russian-speaking Greek AI Companion. Always reply in simple Russian. Use Greek only as examples. "
                        "language teacher."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )


        return (
            response
            .choices[0]
            .message
            .content
            .strip()
        )


    except Exception as error:

        print(
            f"AI LESSON ERROR: {error}"
        )

        return (
            "Sorry, lesson explanation "
            "is unavailable right now."
        )




async def ask_tutor(
    question: str,
    level: str = "A1"
) -> str:
    """
    AI Tutor chat for students.
    """


    try:

        prompt = f"""
Student question:

{question}


Answer requirements:

- Student level: {level}
- Explain in simple Russian.
- Use Greek examples when useful.
- Add pronunciation help if needed.
- Keep answer short and clear.
- Teach like a friendly Greek tutor.
"""


        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.4,
            messages=[{"role": "system", "content": SIMPLE_TEACHING},
                {
                    "role": "system", "name": "teacher",
                    "content": (
                        "You are a friendly Greek AI Companion Tutor. Always answer in Russian, understand emotions, and continue learning with a small practice activity. "
                        "helping A1 beginner students."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )


        return (
            response
            .choices[0]
            .message
            .content
            .strip()
        )


    except Exception as error:

        print(
            f"AI TUTOR ERROR: {error}"
        )

        return (
            "I am unable to answer right now. "
            "Please try again."
        )

async def companion_chat(message: str, context: str = "") -> str:
    """
    AI companion conversation for natural tutor style.
    """
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,
        messages=[{"role": "system", "content": SIMPLE_TEACHING},
            {
                "role":"system",
                "content":(
                    "You are a friendly Greek language companion tutor. "
                    "Talk naturally like a video call teacher. "
                    "Ask about mood, continue conversation, correct mistakes, "
                    "and create practice activities. Never use hardcoded lessons."
                )
            },
            {
                "role":"user",
                "content": f"Context: {context}\nStudent: {message}"
            }
        ]
    )
    return response.choices[0].message.content
