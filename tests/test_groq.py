import os

from dotenv import load_dotenv
from groq import Groq


load_dotenv()

client = Groq(
    api_key=os.environ["GROQ_API_KEY"]
)

response = client.chat.completions.create(
    model=os.environ.get(
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    ),
    messages=[
        {
            "role": "user",
            "content": "Say exactly: ParcelPilot backend is working."
        }
    ],
    temperature=0,
)

print(response.choices[0].message.content)