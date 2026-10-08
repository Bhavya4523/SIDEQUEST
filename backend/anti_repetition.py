import json
import re
from difflib import SequenceMatcher

from backend.models import QuestHistory


STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "your",
    "you",
    "one",
    "with",
    "for",
    "is",
    "from",
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def meaningful_words(text: str) -> set[str]:
    words = normalize(text).split()

    return {
        word
        for word in words
        if len(word) > 2 and word not in STOP_WORDS
    }


def similarity_score(text_a: str, text_b: str) -> float:
    words_a = meaningful_words(text_a)
    words_b = meaningful_words(text_b)

    if not words_a or not words_b:
        return 0.0

    overlap = len(words_a & words_b)
    union = len(words_a | words_b)

    jaccard = overlap / union if union else 0.0

    sequence = SequenceMatcher(
        None,
        normalize(text_a),
        normalize(text_b),
    ).ratio()

    return max(jaccard, sequence)


def build_quest_text(
    title: str,
    objective: str,
    steps: list[str],
) -> str:
    return " ".join([
        title,
        objective,
        " ".join(steps),
    ])


def check_repetition(
    db,
    title: str,
    objective: str,
    steps: list[str],
    category: str,
    recent_limit: int = 10,
    similarity_threshold: float = 0.72,
):
    history = (
        db.query(QuestHistory)
        .order_by(QuestHistory.created_at.desc())
        .limit(recent_limit)
        .all()
    )

    candidate_text = build_quest_text(
        title,
        objective,
        steps,
    )

    exact_duplicate = False
    too_similar = False
    most_similar_score = 0.0

    for past_quest in history:
        past_steps = json.loads(
            past_quest.steps
        )

        past_text = build_quest_text(
            past_quest.title,
            past_quest.objective,
            past_steps,
        )

        score = similarity_score(
            candidate_text,
            past_text,
        )

        most_similar_score = max(
            most_similar_score,
            score,
        )

        if normalize(title) == normalize(
            past_quest.title
        ):
            exact_duplicate = True

        if score >= similarity_threshold:
            too_similar = True

    recent_categories = [
        quest.category.lower()
        for quest in history[:3]
    ]

    category_repeated = (
        category.lower() in recent_categories
    )

    return {
        "exact_duplicate": exact_duplicate,
        "too_similar": too_similar,
        "category_repeated": category_repeated,
        "similarity_score": round(
            most_similar_score,
            3,
        ),
        "allowed": not (
            exact_duplicate
            or too_similar
        ),
    }