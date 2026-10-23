from services.teaching_policy import SIMPLE_TEACHING
import json
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI


load_dotenv()


client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-4.1-mini"
)



async def generate_exercises(
    topic: str,
    grammar: str = "",
    vocabulary: str = "",
    level: str = "A1",
    amount: int = 5
) -> list[dict]:

    """
    Generate Greek language exercises using AI.
    """

    prompt = f"""
You are a Greek language teacher.

Create {amount} beginner Greek exercises based ONLY on the current lesson.

Student level:
{level}

Topic:
{topic}

Grammar:
{grammar}

Vocabulary:
{vocabulary}


Return ONLY valid JSON array.

Format:

[
  {{
    "question": "Translate Good morning into Greek",
    "type": "translation",
    "correct_answer": "Καλημέρα"
  }}
]


Rules:
- Use A1 beginner Greek.
- Use ONLY the provided lesson content. The current lesson content from Supabase is the single source of truth.
- Cover the important points from the Supabase lesson content. Do not skip required vocabulary, grammar, pronunciation, meanings, or examples that are part of this lesson.
- Do not introduce a new topic, future lesson content, or unrelated Greek words.
- Match the exercise difficulty with the current lesson level.

QUESTION TYPE RULES:
- Decide intelligently between open-ended and multiple-choice questions.
- Use multiple-choice ONLY when the question naturally requires recognition or choosing between possible answers.
- Questions like:
  "Which of the following means..."
  "Which of the following is correct..."
  "Choose the correct Greek word..."
  "Which sentence is correct..."
  should normally include options.
- For multiple-choice questions provide exactly 3 or 4 options.
- Only ONE option can be correct.
- The correct_answer must exactly match one option.

- Do NOT add options for:
  - translation where the student should write the answer
  - sentence building
  - speaking practice
  - pronunciation production
  - writing exercises

JSON FORMAT:
For multiple-choice:
{
  "question": "...",
  "type": "multiple_choice",
  "options": ["option 1", "option 2", "option 3", "option 4"],
  "correct_answer": "correct option"
}

For open-ended:
{
  "question": "...",
  "type": "translation",
  "options": [],
  "correct_answer": "answer"
}

Additional rules:
- Create different exercise styles when possible.
- Keep questions simple and suitable for beginners.
- Do not use old examples unless they exist in the current lesson.
- Do not add markdown.
- Do not add explanations outside JSON.
"""


    try:

        response = await client.chat.completions.create(

            model=OPENAI_MODEL,

            temperature=0.3,

            messages=[{"role": "system", "content": SIMPLE_TEACHING},

                {
                    "role": "system", "name": "teacher",
                    "content":
                    "You create beginner Greek exercises and output JSON only."
                },

                {
                    "role": "user",
                    "content": prompt
                }

            ]
        )


        content = (
            response
            .choices[0]
            .message
            .content
        )


        if not content:
            return []


        # Remove markdown if AI adds ```json
        content = (
            content
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )


        exercises = json.loads(content)


        if not isinstance(exercises, list):
            return []


        return exercises[:amount]


    except Exception as error:

        print(
            f"EXERCISE GENERATOR ERROR: {error}"
        )

        return []