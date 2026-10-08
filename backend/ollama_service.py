import json

import httpx

from backend.schemas import Quest


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "gemma3:4b"

async def generate_quest(
    prompt: str,
    temperature: float = 0,
) -> Quest:
    system_prompt = """
You are SIDEQUEST, a real-world adventure generator.

Create safe, practical, interesting sidequests that encourage the user
to spend less time on their phone and experience the real world.

Return ONLY valid JSON matching the provided schema.

IMPORTANT:
- duration_minutes must be a positive integer.
- novelty_score MUST be a decimal number between 0.0 and 1.0.
- Never use a 1-10 scale for novelty_score.
- difficulty should be "easy", "medium", or "hard".
- Include at least one step.
- Include at least one safety note.
"""

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "format": Quest.model_json_schema(),
        "options": {
            "temperature":  temperature,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(2):
            response = await client.post(
                OLLAMA_URL,
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            content = data["message"]["content"]

            try:
                return Quest.model_validate(json.loads(content))
            except Exception as exc:
                if attempt == 1:
                    raise ValueError(
                        f"Gemma returned invalid quest data: {exc}"
                    ) from exc

                payload["messages"].append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous output failed validation. "
                            "Regenerate the quest and make absolutely sure "
                            "novelty_score is between 0.0 and 1.0. "
                            "Return JSON only."
                        ),
                    }
                )

    raise RuntimeError("Quest generation failed.")