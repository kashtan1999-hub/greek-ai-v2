from services.teaching_policy import SIMPLE_TEACHING
import os
import tempfile

from openai import AsyncOpenAI


client = AsyncOpenAI(
    api_key=os.getenv(
        "OPENAI_API_KEY"
    )
)



async def generate_voice_feedback(
    analysis,
    context: dict
):


    block = context.get(
        "block"
    )


    topic = context.get(
        "topic"
    )


    step = context.get(
        "step"
    )



    prompt = f"""

You are a Greek language speaking tutor.


Student current learning context:


Block:
{block}


Topic:
{topic}


Step:
{step}



Student pronunciation analysis:

{analysis}



Rules:

- Follow only the current topic.
- Never use fixed examples.
- Adjust difficulty according to block and step.
- Explain feedback in Russian.
- Keep Greek words only when needed.
- Student is learning Greek.
- Give short encouraging feedback.
- Explain pronunciation mistakes clearly.


Create only the voice speaking script.

"""



    response = await client.chat.completions.create(

        model="gpt-4.1-mini",

        temperature=0,

        messages=[{"role": "system", "content": SIMPLE_TEACHING},

            {
                "role": "user",
                "content": prompt
            }

        ]

    )



    text = (

        response
        .choices[0]
        .message
        .content
        .strip()

    )



    audio = await client.audio.speech.create(

        model="gpt-4o-mini-tts",

        voice="alloy",

        input=text

    )



    path = tempfile.NamedTemporaryFile(

        suffix=".mp3",

        delete=False

    ).name



    audio.stream_to_file(
        path
    )


    return path