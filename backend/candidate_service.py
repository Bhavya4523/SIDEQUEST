from backend.anti_repetition import (
    build_quest_text,
    similarity_score,
)
from backend.ollama_service import generate_quest
from backend.quest_filter import validate_quest


CANDIDATE_FOCUSES = [
    "exploration and discovery",
    "food and local culture",
    "observation and architecture",
]


async def generate_candidates(
    base_prompt: str,
    count: int = 3,
):
    candidates = []

    for index in range(count):
        focus = CANDIDATE_FOCUSES[
            index % len(CANDIDATE_FOCUSES)
        ]

        prompt = f"""
{base_prompt}

This is candidate {index + 1}.

This candidate must have a clearly different approach
from the other possible candidates.

Primary focus for this candidate:
{focus}

Do NOT simply rephrase a generic quest.
Create a meaningfully different activity.

Make the quest:
- practical
- safe
- achievable within the available time
- interesting in the real world
- stay in public areas
- do not require the user to use their phone during the quest
- avoid online research
- avoid activities that encourage prolonged screen use
- different from the other candidate types
"""

        quest = await generate_quest(
            prompt,
            temperature=0.7,
        )

        candidates.append(quest)

    # Remove unsafe or screen-dependent candidates.
    safe_candidates = [
        candidate
        for candidate in candidates
        if validate_quest(candidate)["allowed"]
    ]

    # Remove candidates that are too similar
    # to another candidate in the same batch.
    diverse_candidates = []

    for candidate in safe_candidates:
        candidate_text = build_quest_text(
            candidate.title,
            candidate.objective,
            candidate.steps,
        )

        is_duplicate = False

        for existing in diverse_candidates:
            existing_text = build_quest_text(
                existing.title,
                existing.objective,
                existing.steps,
            )

            score = similarity_score(
                candidate_text,
                existing_text,
            )

            if score >= 0.72:
                is_duplicate = True
                break

        if not is_duplicate:
            diverse_candidates.append(candidate)

    return diverse_candidates