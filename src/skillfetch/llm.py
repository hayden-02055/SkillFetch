"""Single-provider LLM call (OpenAI SDK) returning a JSON object."""

import json
import os

from openai import OpenAI, OpenAIError

DEFAULT_MODEL = "gpt-5.4-mini"


class LLMError(Exception):
    pass


def chat_json(system: str, user: str) -> dict:
    """Send one chat request in JSON mode. Reads OPENAI_API_KEY / OPENAI_BASE_URL from env."""
    model = os.environ.get("SKILLFETCH_MODEL", DEFAULT_MODEL)
    try:
        client = OpenAI(timeout=60.0)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
    except OpenAIError as exc:
        raise LLMError(f"LLM API call failed: {exc}") from exc

    content = (response.choices[0].message.content if response.choices else None) or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMError("LLM returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise LLMError("LLM returned JSON that is not an object.")
    return data
