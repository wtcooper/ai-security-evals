from dotenv import load_dotenv; load_dotenv()
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.getenv("LITELLM_BASE_URL", "http://localhost:4000"), api_key=os.getenv("LITELLM_API_KEY", "sk-mock")
    )
model = "gemma4:e2b"  # gemma4 qwen3.5

def get_response(prompt):
    result = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return result.choices[0].message.content

response = get_response("What is the capital of France?")
response
