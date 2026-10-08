import json
import os
import re
from typing import Any

import httpx
from pydantic import ValidationError

from backend.schemas import Quest


# Modes:
#   ollama     -> local only
#   openrouter -> hosted only
#   huggingface -> Hugging Face only
#   auto       -> local Ollama first, hosted OpenRouter fallback
AI_MODE = os.getenv("AI_MODE", "auto").strip().lower()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "5"))

HF_MODEL = os.getenv("HF_MODEL", "google/gemma-3-4b-it")
HF_TOKEN = os.getenv("HF_TOKEN")
HF_TIMEOUT = float(os.getenv("HF_TIMEOUT", "90"))

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

Create ONE safe, feasible, interesting sidequest that gets the user away
from their phone and into the physical world.

Rules:
- Return ONLY one valid JSON object. No Markdown and no commentary.
- Required fields: title, duration_minutes, difficulty, category, objective,
  steps, novelty_score, safety_notes.
- duration_minutes must be a positive integer and must not exceed available time.
- novelty_score must be between 0.0 and 1.0.
- difficulty must be exactly one of: easy, medium, hard.
- Keep the quest possible in ordinary public surroundings.
- Never require private property, trespassing, dangerous roads, climbing,
  unsafe isolation, wildlife approach, illegal activity, or dangerous weather.
- Never require Google Maps, browsing, online research, photography,
  recording, or continuous phone use.
- Prefer walking, observation, local culture, food, architecture,
  curiosity, and discovery.
- Avoid repetitive generic missions.
- Make it feel spontaneous and human.
- safety_notes must include concise real-world precautions.
""".strip()


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()

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
    return Quest.model_validate(_extract_json(content))


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts).strip()

    return ""


def _fallback_quest(prompt: str) -> Quest:
    """Last-resort safe quest so the app never becomes unusable during an AI outage."""
    match = re.search(r"Available time:\s*(\d+)", prompt, re.IGNORECASE)
    available = int(match.group(1)) if match else 20
    duration = max(1, min(15, available))

    lower = prompt.lower()
    if "food and local culture" in lower:
        return Quest(
            title="The Local Bite",
            duration_minutes=duration,
            difficulty="easy",
            category="food",
            objective="Notice one local food or drink you would normally walk past, then continue your journey.",
            steps=[
                "Take a slightly different public path for a few minutes.",
                "Look for a local food or drink you have not noticed before.",
                "Observe one small detail about how it is prepared or presented.",
                "Continue toward your destination without using your phone.",
            ],
            novelty_score=0.78,
            safety_notes=[
                "Stay on public paths and away from traffic.",
                "Do not enter restricted or private areas.",
                "Skip the quest if weather or surroundings feel unsafe.",
            ],
        )

    if "observation and architecture" in lower:
        return Quest(
            title="Look Up, Look Around",
            duration_minutes=duration,
            difficulty="easy",
            category="architecture",
            objective="Notice an architectural detail on a public street that you normally miss.",
            steps=[
                "Take a slightly unfamiliar public path for a few minutes.",
                "Look for one doorway, balcony, sign, window, or facade with a distinctive detail.",
                "Notice a second detail nearby that contrasts with it.",
                "Continue toward your destination without using your phone.",
            ],
            novelty_score=0.81,
            safety_notes=[
                "Stay on sidewalks and public paths.",
                "Do not enter private property.",
                "Keep clear of traffic and unsafe crossings.",
            ],
        )

    return Quest(
        title="The Unfamiliar Turn",
        duration_minutes=duration,
        difficulty="easy",
        category="exploration",
        objective="Interrupt your usual route long enough to notice something genuinely unfamiliar.",
        steps=[
            "Leave your normal path at the next safe opportunity.",
            "Walk until you find one street, corner, or public space you have not noticed before.",
            "Find one small detail that makes the place feel different from your routine.",
            "Turn back toward your destination before your time window runs out.",
        ],
        novelty_score=0.84,
        safety_notes=[
            "Stay in public, familiar-enough areas.",
            "Avoid busy roads and unsafe crossings.",
            "Use your judgment and end the quest if conditions feel unsafe.",
        ],
    )


async def _generate_with_ollama(prompt: str, temperature: float) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": Quest.model_json_schema(),
        "options": {"temperature": temperature},
    }

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        response = await client.post(OLLAMA_URL, json=payload)

    response.raise_for_status()
    data = response.json()
    content = (data.get("message", {}).get("content", "") or "").strip()

    if not content:
        raise ValueError("Local model returned empty output.")

    return content


async def _generate_with_huggingface(prompt: str, temperature: float) -> str:
    if not HF_TOKEN:
        raise RuntimeError("HF_TOKEN is not configured for hosted AI mode.")

    try:
        from huggingface_hub import AsyncInferenceClient
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is not installed.") from exc

    client = AsyncInferenceClient(
        model=HF_MODEL,
        token=HF_TOKEN,
        provider="auto",
        timeout=HF_TIMEOUT,
    )

    response = await client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": prompt + "\n\nReturn ONLY the JSON object.",
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


async def _generate_with_openrouter(prompt: str, temperature: float) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    # Deliberately use prompt-constrained JSON instead of response_format.
    # This is more compatible with OpenRouter's free routed providers.
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
        raise RuntimeError(
            f"OpenRouter HTTP {response.status_code}: {response.text[:800]}"
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


async def _generate_once(prompt: str, temperature: float) -> Quest:
    if AI_MODE == "ollama":
        return _validate_quest(await _generate_with_ollama(prompt, temperature))
    if AI_MODE == "huggingface":
        return _validate_quest(await _generate_with_huggingface(prompt, temperature))
    if AI_MODE == "openrouter":
        return _validate_quest(await _generate_with_openrouter(prompt, temperature))
    if AI_MODE == "auto":
        # Local first: this is what makes the same codebase genuinely usable
        # with Wi-Fi OFF when Ollama is running on the user's machine.
        try:
            return _validate_quest(await _generate_with_ollama(prompt, temperature))
        except Exception as local_exc:
            print(
                f"SIDEQUEST local AI unavailable in auto mode: "
                f"{type(local_exc).__name__}: {local_exc}",
                flush=True,
            )

        # Hosted fallback keeps the public Render deployment usable.
        return _validate_quest(
            await _generate_with_openrouter(prompt, temperature)
        )

    raise RuntimeError(
        "Invalid AI_MODE. Use 'auto', 'ollama', 'openrouter', or 'huggingface'."
    )


async def generate_quest(prompt: str, temperature: float = 0) -> Quest:
    """Generate a validated quest with retries and a final safe fallback."""
    last_error: Exception | None = None

    for attempt in range(2):
        retry_prompt = prompt
        if attempt:
            retry_prompt += """

IMPORTANT RETRY:
Return exactly one JSON object with every required field.
Do not add commentary or Markdown.
Keep duration_minutes within the available time.
Keep novelty_score between 0.0 and 1.0.
"""

        try:
            return await _generate_once(retry_prompt, temperature)
        except (ValidationError, ValueError, json.JSONDecodeError, httpx.HTTPError) as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc

    # Provider failure should not make the product unusable. This fallback is
    # only reached after the AI paths have failed and is intentionally simple.
    print(
        "SIDEQUEST using safe fallback after AI failure: "
        f"{type(last_error).__name__}: {last_error}",
        flush=True,
    )
    return _fallback_quest(prompt)
