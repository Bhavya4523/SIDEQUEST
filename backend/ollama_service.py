import json
import os
from typing import Any

import httpx
from pydantic import ValidationError

from backend.schemas import Quest


AI_MODE = os.getenv("AI_MODE", "ollama").strip().lower()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",
)
OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "gemma3:4b",
)

HF_MODEL = os.getenv(
    "HF_MODEL",
    "google/gemma-3-4b-it",
)
HF_TOKEN = os.getenv("HF_TOKEN")
HF_TIMEOUT = float(os.getenv("HF_TIMEOUT", "90"))

OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "90"))

OPENROUTER_URL = os.getenv(
    "OPENROUTER_URL",
    "https://openrouter.ai/api/v1/chat/completions",
)
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "google/gemma-3-4b-it:free",
)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT", "90"))


SYSTEM_PROMPT = """
You are SIDEQUEST, an AI that creates tiny real-world adventures.

Your job is to create safe, feasible, interesting sidequests that get the
user away from their phone and into the physical world.

Rules:
- Return ONLY valid JSON matching the requested schema.
- duration_minutes must be a positive integer.
- novelty_score must be a decimal between 0.0 and 1.0.
- difficulty should be one of: easy, medium, hard.
- The quest must fit the user's available time.
- Prefer public, ordinary, safe places.
- Never require private property, trespassing, dangerous roads,
  dangerous climbing, unsafe isolation, wildlife approach, illegal activity,
  or dangerous weather conditions.
- Do not require Google Maps, online research, browsing, photography,
  recording, or continuous phone use.
- Do not create generic repetitive missions.
- The mission should be possible using observation, walking, curiosity,
  local surroundings, food, architecture, people, or discovery.
- Make the quest feel spontaneous and human rather than like a checklist app.

Required JSON fields:
title
duration_minutes
difficulty
category
objective
steps
novelty_score
safety_notes
"""


def _extract_json(text: str) -> dict[str, Any]:
    """Extract one JSON object from model output."""
    text = text.strip()

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not contain a JSON object.")

    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("Model returned malformed JSON.") from exc

    if not isinstance(value, dict):
        raise ValueError("Model response was not a JSON object.")

    return value


def _validate_quest(content: str) -> Quest:
    payload = _extract_json(content)
    return Quest.model_validate(payload)


def _content_to_text(content: Any) -> str:
    """Normalize Hugging Face message content to plain text."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    return ""


async def _generate_with_ollama(
    prompt: str,
    temperature: float,
) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "format": Quest.model_json_schema(),
        "options": {
            "temperature": temperature,
        },
    }

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(
            OLLAMA_URL,
            json=payload,
        )

    response.raise_for_status()

    data = response.json()
    content = (
        data.get("message", {})
        .get("content", "")
        .strip()
    )

    if not content:
        raise ValueError("Local model returned empty output.")

    return content


async def _generate_with_huggingface(
    prompt: str,
    temperature: float,
) -> str:
    if not HF_TOKEN:
        raise RuntimeError(
            "HF_TOKEN is not configured for hosted AI mode."
        )

    try:
        from huggingface_hub import AsyncInferenceClient
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is not installed."
        ) from exc

    client = AsyncInferenceClient(
        model=HF_MODEL,
        token=HF_TOKEN,
        provider="auto",
        timeout=HF_TIMEOUT,
    )

    response = await client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    prompt
                    + "\n\nReturn ONLY the JSON object. "
                    "Do not use Markdown fences."
                ),
            },
        ],
        temperature=temperature,
        max_tokens=700,
    )

    if not response.choices:
        raise ValueError("Hosted model returned no choices.")

    content = _content_to_text(response.choices[0].message.content)

    if not content:
        raise ValueError("Hosted model returned empty output.")

    return content


async def _generate_with_openrouter(
    prompt: str,
    temperature: float,
) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured for hosted AI mode."
        )

    schema = Quest.model_json_schema()
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    prompt
                    + "\n\nReturn ONLY the JSON object. "
                    "Do not use Markdown fences."
                ),
            },
        ],
        "temperature": temperature,
        "max_tokens": 700,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "sidequest",
                "strict": True,
                "schema": schema,
            },
        },
        "provider": {
            "require_parameters": True,
        },
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://sidequest-jstk.onrender.com",
        "X-Title": "SIDEQUEST",
    }

    async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
        )

    if response.is_error:
        detail = response.text[:1000]
        raise RuntimeError(
            f"OpenRouter HTTP {response.status_code}: {detail}"
        )

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter returned no choices.")

    message = choices[0].get("message") or {}
    content = _content_to_text(message.get("content"))

    if not content:
        raise ValueError("OpenRouter returned empty output.")

    return content


async def generate_quest(
    prompt: str,
    temperature: float = 0,
) -> Quest:
    """
    Generate and validate a SIDEQUEST quest.

    AI_MODE=ollama:
        Uses local Ollama + Gemma.

    AI_MODE=huggingface:
        Uses Hugging Face Inference Providers + Gemma.

    AI_MODE=openrouter:
        Uses OpenRouter + Gemma 3 4B free endpoint.
    """
    if AI_MODE not in {"ollama", "huggingface", "openrouter"}:
        raise RuntimeError(
            "Invalid AI_MODE. Use 'ollama', 'huggingface', or 'openrouter'."
        )

    last_error: Exception | None = None

    for attempt in range(2):
        retry_prompt = prompt

        if attempt > 0:
            retry_prompt += """

IMPORTANT:
The previous response failed validation.

Return a single valid JSON object.
Make sure novelty_score is between 0.0 and 1.0.
Make sure duration_minutes is a positive integer.
Include every required field.
"""

        try:
            if AI_MODE == "huggingface":
                content = await _generate_with_huggingface(
                    retry_prompt,
                    temperature,
                )
            elif AI_MODE == "openrouter":
                content = await _generate_with_openrouter(
                    retry_prompt,
                    temperature,
                )
            else:
                content = await _generate_with_ollama(
                    retry_prompt,
                    temperature,
                )

            return _validate_quest(content)

        except (
            ValidationError,
            ValueError,
            json.JSONDecodeError,
            httpx.HTTPError,
        ) as exc:
            last_error = exc

        except Exception as exc:
            last_error = exc

    if last_error is None:
        raise RuntimeError("AI generation failed without a reported error.")

    raise RuntimeError(
        "AI generation failed after retry: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error
