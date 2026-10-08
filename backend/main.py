import json
import os
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.database import Base, engine, get_db
from backend.models import QuestHistory
from backend.ollama_service import (
    AI_MODE,
    HF_MODEL,
    OLLAMA_MODEL,
    OPENROUTER_MODEL,
    generate_quest,
)
from backend.schemas import ChaosRequest, Quest, QuestFeedback, QuestRequest


# Render starts with a fresh SQLite database. Create all tables at startup.
Base.metadata.create_all(bind=engine)


def _init_user_tables() -> None:
    """Create anonymous-user tables without changing the existing schema."""
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS sidequest_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL UNIQUE,
                category_preferences TEXT NOT NULL DEFAULT '{}',
                preferred_duration INTEGER NOT NULL DEFAULT 20,
                preferred_difficulty TEXT NOT NULL DEFAULT 'easy',
                novelty_preference REAL NOT NULL DEFAULT 0.70
            )
        """))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS sidequest_user_quests (
                user_id INTEGER NOT NULL,
                quest_id INTEGER NOT NULL UNIQUE,
                PRIMARY KEY (user_id, quest_id),
                FOREIGN KEY(user_id) REFERENCES sidequest_users(id),
                FOREIGN KEY(quest_id) REFERENCES quest_history(id)
            )
        """))


_init_user_tables()

app = FastAPI(title="SIDEQUEST API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://sidequest-jstk.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SAFE_BLOCKED_PHRASES = [
    "use your phone",
    "use phone",
    "take a photo",
    "take photo",
    "photograph",
    "google maps",
    "research online",
    "search online",
    "private property",
    "trespass",
    "trespassing",
    "dangerous climbing",
    "unsafe road",
    "busy road",
    "approach wildlife",
    "feed wildlife",
    "touch wildlife",
    "follow animal",
    "animal trail",
    "illegal activity",
]

FOCUS_AREAS = [
    "exploration and discovery",
    "food and local culture",
    "observation and architecture",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _loads(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _clean_text(value: str, limit: int = 500) -> str:
    value = (value or "").strip()
    return value[:limit]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def _quest_text(quest: Quest) -> str:
    return " ".join(
        [
            quest.title,
            quest.objective,
            quest.category,
            *quest.steps,
        ]
    )


def _is_safe(quest: Quest) -> tuple[bool, str | None]:
    text = _normalise(_quest_text(quest))
    for phrase in SAFE_BLOCKED_PHRASES:
        if _normalise(phrase) in text:
            return False, phrase
    return True, None


def _client_id(value: str | None) -> str:
    """Normalize the anonymous browser identifier."""
    value = (value or "").strip()
    return value[:128] if value else "api-anonymous"


def _ensure_user(db: Session, client_id: str):
    client_id = _client_id(client_id)
    row = db.execute(
        text(
            "SELECT id, client_id, category_preferences, preferred_duration, "
            "preferred_difficulty, novelty_preference "
            "FROM sidequest_users WHERE client_id = :client_id"
        ),
        {"client_id": client_id},
    ).mappings().first()

    if row is None:
        db.execute(
            text(
                "INSERT INTO sidequest_users "
                "(client_id, category_preferences, preferred_duration, "
                "preferred_difficulty, novelty_preference) "
                "VALUES (:client_id, '{}', 20, 'easy', 0.70)"
            ),
            {"client_id": client_id},
        )
        db.commit()
        row = db.execute(
            text(
                "SELECT id, client_id, category_preferences, preferred_duration, "
                "preferred_difficulty, novelty_preference "
                "FROM sidequest_users WHERE client_id = :client_id"
            ),
            {"client_id": client_id},
        ).mappings().first()

    return row


def _profile_data(db: Session, client_id: str) -> dict:
    user = _ensure_user(db, client_id)
    return {
        "category_preferences": _loads(user["category_preferences"], {}),
        "preferred_duration": user["preferred_duration"],
        "preferred_difficulty": user["preferred_difficulty"],
        "novelty_preference": user["novelty_preference"],
    }


def _recent_history(
    db: Session,
    client_id: str,
    limit: int = 10,
) -> list[QuestHistory]:
    user = _ensure_user(db, client_id)
    quest_ids = db.execute(
        text(
            "SELECT quest_id FROM sidequest_user_quests "
            "WHERE user_id = :user_id ORDER BY quest_id DESC LIMIT :limit"
        ),
        {"user_id": user["id"], "limit": limit},
    ).scalars().all()

    if not quest_ids:
        return []

    return (
        db.query(QuestHistory)
        .filter(QuestHistory.id.in_(quest_ids))
        .order_by(QuestHistory.created_at.desc(), QuestHistory.id.desc())
        .all()
    )


def _is_repetitive(db: Session, client_id: str, quest: Quest) -> bool:
    recent = _recent_history(db, client_id, 10)
    new_text = _normalise(_quest_text(quest))

    for record in recent:
        old_text = _normalise(
            " ".join(
                [
                    record.title,
                    record.objective,
                    record.category,
                    *_loads(record.steps, []),
                ]
            )
        )

        if _normalise(record.title) == _normalise(quest.title):
            return True

        similarity = SequenceMatcher(None, old_text, new_text).ratio()
        if similarity >= 0.82:
            return True

    return False


def _build_prompt(
    *,
    destination: str,
    time_available: int,
    mood: str,
    interests: list[str],
    profile_data: dict,
    recent: list[QuestHistory],
    focus: str,
    chaos: bool = False,
) -> str:
    recent_summary = []
    for record in recent:
        recent_summary.append(
            {
                "title": record.title,
                "category": record.category,
                "status": record.status,
            }
        )

    return f"""
Create one SIDEQUEST.

Journey context:
Destination: {_clean_text(destination, 180)}
Available time: {int(time_available)} minutes
Mood: {_clean_text(mood, 80)}
Interests: {json.dumps(interests[:8], ensure_ascii=False)}

Personalization profile:
{json.dumps(profile_data, ensure_ascii=False)}

Recent quest history to avoid:
{json.dumps(recent_summary, ensure_ascii=False)}

Design focus for this candidate:
{focus}

Mode:
{"CHAOS MODE — prioritize surprise and novelty while remaining safe and feasible." if chaos else "PERSONALIZED MODE — balance preference with novelty and feasibility."}

The quest must fit the available time, be possible without a phone, and be safe
in ordinary public surroundings. Do not assume the destination is a specific
building, route, shop, or landmark unless the user explicitly named it.
""".strip()


def _time_score(duration: int, available: int) -> float:
    if duration <= 0 or available <= 0:
        return 0.0
    if duration > available:
        return 0.0
    spare = available - duration
    return max(0.0, 1.0 - (spare / available) * 0.8)


def _preference_score(quest: Quest, profile_data: dict, interests: list[str]) -> float:
    prefs = profile_data.get("category_preferences", {}) or {}
    category = quest.category.lower()
    score = float(prefs.get(category, 0.5))

    for interest in interests:
        if interest.lower() in category or category in interest.lower():
            score = min(1.0, score + 0.15)
    return max(0.0, min(1.0, score))


def _historical_success(quest: Quest, history: list[QuestHistory]) -> float:
    same = [r for r in history if r.category == quest.category]
    if not same:
        return 0.5
    completed = sum(r.status == "completed" for r in same)
    return completed / len(same)


def _rank_quest(
    quest: Quest,
    *,
    time_available: int,
    interests: list[str],
    profile_data: dict,
    history: list[QuestHistory],
) -> float:
    time_fit = _time_score(quest.duration_minutes, time_available)
    preference = _preference_score(quest, profile_data, interests)
    novelty = quest.novelty_score
    feasibility = 1.0 if quest.duration_minutes <= time_available else 0.0
    route_compatibility = 0.5
    historical_success = _historical_success(quest, history)

    recent_categories = [record.category for record in history[:3]]
    category_recency_penalty = 0.08 if quest.category in recent_categories else 0.0

    score = (
        0.25 * time_fit
        + 0.20 * preference
        + 0.20 * novelty
        + 0.15 * feasibility
        + 0.10 * route_compatibility
        + 0.10 * historical_success
    )

    if _is_repetitive_score(db=None, quest=quest):
        score -= 0.15

    score -= category_recency_penalty

    return max(0.0, min(1.0, score))


def _is_repetitive_score(db, quest: Quest) -> bool:
    # Placeholder used only to keep ranking deterministic; actual repetition is
    # checked against the database before selection.
    return False


async def _generate_candidates(
    db: Session,
    client_id: str,
    *,
    destination: str,
    time_available: int,
    mood: str,
    interests: list[str],
    count: int,
    chaos: bool = False,
) -> list[tuple[Quest, float]]:
    profile_data = _profile_data(db, client_id)
    history = _recent_history(db, client_id, 10)
    results: list[tuple[Quest, float]] = []

    for index in range(count):
        focus = FOCUS_AREAS[index % len(FOCUS_AREAS)]
        prompt = _build_prompt(
            destination=destination,
            time_available=time_available,
            mood=mood,
            interests=interests,
            profile_data=profile_data,
            recent=history,
            focus=focus,
            chaos=chaos,
        )

        try:
            quest = await generate_quest(
                prompt,
                temperature=0.7 if count > 1 else 0.5,
            )
        except Exception as exc:
            print(
                f"SIDEQUEST candidate {index + 1} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        safe, _ = _is_safe(quest)
        if not safe:
            continue

        if quest.duration_minutes > time_available:
            continue

        if _is_repetitive(db, client_id, quest):
            continue

        score = _rank_quest(
            quest,
            time_available=time_available,
            interests=interests,
            profile_data=profile_data,
            history=history,
        )
        results.append((quest, score))

    return results


def _history_dict(record: QuestHistory) -> dict:
    return {
        "id": record.id,
        "destination": record.destination,
        "time_available": record.time_available,
        "mood": record.mood,
        "interests": _loads(record.interests, []),
        "title": record.title,
        "duration_minutes": record.duration_minutes,
        "difficulty": record.difficulty,
        "category": record.category,
        "objective": record.objective,
        "steps": _loads(record.steps, []),
        "novelty_score": record.novelty_score,
        "safety_notes": _loads(record.safety_notes, []),
        "status": record.status,
        "rating": record.rating,
        "reflection": record.reflection,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _save_quest(
    db: Session,
    client_id: str,
    *,
    request_destination: str,
    time_available: int,
    mood: str,
    interests: list[str],
    quest: Quest,
) -> QuestHistory:
    history = QuestHistory(
        destination=request_destination,
        time_available=time_available,
        mood=mood,
        interests=_dumps(interests),
        title=quest.title,
        duration_minutes=quest.duration_minutes,
        difficulty=quest.difficulty,
        category=quest.category,
        objective=quest.objective,
        steps=_dumps(quest.steps),
        novelty_score=quest.novelty_score,
        safety_notes=_dumps(quest.safety_notes),
        status="attempted",
        rating=None,
        reflection=None,
        created_at=_now(),
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    user = _ensure_user(db, client_id)
    db.execute(
        text(
            "INSERT INTO sidequest_user_quests (user_id, quest_id) "
            "VALUES (:user_id, :quest_id)"
        ),
        {"user_id": user["id"], "quest_id": history.id},
    )
    db.commit()
    return history


def _update_profile(db: Session, client_id: str, record: QuestHistory) -> None:
    user = _ensure_user(db, client_id)
    preferences = _loads(user["category_preferences"], {})
    category = record.category
    current = float(preferences.get(category, 0.5))

    if record.status == "completed":
        reward = 0.20
        if record.rating is not None:
            reward += (record.rating - 3) * 0.05
    elif record.status == "partly":
        reward = 0.04
    else:
        reward = -0.12

    preferences[category] = max(0.05, min(0.95, current + reward))

    owned_completed = db.execute(
        text(
            "SELECT COUNT(*) FROM sidequest_user_quests uq "
            "JOIN quest_history qh ON qh.id = uq.quest_id "
            "WHERE uq.user_id = :user_id AND qh.status = 'completed'"
        ),
        {"user_id": user["id"]},
    ).scalar() or 0

    if record.status == "completed":
        old_duration = float(user["preferred_duration"] or 20)
        preferred_duration = int(round(
            old_duration * 0.8 + record.duration_minutes * 0.2
        ))
    else:
        preferred_duration = user["preferred_duration"]

    novelty = 0.7 if owned_completed == 0 else user["novelty_preference"]

    db.execute(
        text(
            "UPDATE sidequest_users SET category_preferences = :prefs, "
            "preferred_duration = :duration, novelty_preference = :novelty "
            "WHERE id = :user_id"
        ),
        {
            "prefs": _dumps(preferences),
            "duration": preferred_duration,
            "novelty": novelty,
            "user_id": user["id"],
        },
    )
    db.commit()


@app.get("/")
def root():
    return {"name": "SIDEQUEST", "message": "Your destination isn't the point."}


@app.get("/health")
def health():
    if AI_MODE == "huggingface":
        ai = "huggingface"
        model = HF_MODEL
        offline_capable = False
    elif AI_MODE == "openrouter":
        ai = "openrouter"
        model = OPENROUTER_MODEL
        offline_capable = False
    else:
        ai = "local"
        model = OLLAMA_MODEL
        offline_capable = True

    return {
        "status": "healthy",
        "ai": ai,
        "model": model,
        "offline_capable": offline_capable,
    }


@app.post("/generate-quest")
async def create_quest(request: QuestRequest, db: Session = Depends(get_db), client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID")):
    client_id = _client_id(client_header)
    try:
        candidates = await _generate_candidates(
            db,
            client_id,
            destination=request.destination,
            time_available=request.time_available,
            mood=request.mood,
            interests=request.interests,
            count=3,
        )

        if not candidates:
            return {
                "error": (
                    "I couldn't create a safe sidequest right now. "
                    "Please try again with the same journey or a little more time."
                )
            }

        selected, selected_score = max(candidates, key=lambda item: item[1])
        history = _save_quest(
            db,
            client_id,
            request_destination=request.destination,
            time_available=request.time_available,
            mood=request.mood,
            interests=request.interests,
            quest=selected,
        )

        return {
            "id": history.id,
            "score": selected_score,
            "quest": selected.model_dump(),
        }

    except Exception as exc:
        print(
            f"SIDEQUEST generation failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {
            "error": "Sidequest generation failed. Please try again."
        }


@app.post("/generate-candidates")
async def create_candidates(request: QuestRequest, db: Session = Depends(get_db), client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID")):
    client_id = _client_id(client_header)
    try:
        candidates = await _generate_candidates(
            db,
            client_id,
            destination=request.destination,
            time_available=request.time_available,
            mood=request.mood,
            interests=request.interests,
            count=3,
        )
        return {
            "candidates": [
                {"score": score, "quest": quest.model_dump()}
                for quest, score in candidates
            ]
        }
    except Exception as exc:
        print(
            f"SIDEQUEST candidate generation failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {"error": "Candidate generation failed. Please try again."}


@app.get("/quests")
def list_quests(db: Session = Depends(get_db), client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID")):
    client_id = _client_id(client_header)
    records = _recent_history(db, client_id, 100)
    return [_history_dict(record) for record in records]


@app.post("/quests/{quest_id}/feedback")
def quest_feedback(
    quest_id: int,
    feedback: QuestFeedback,
    db: Session = Depends(get_db),
    client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID"),
):
    client_id = _client_id(client_header)
    record = db.get(QuestHistory, quest_id)
    if record is None:
        return {"error": "Quest not found."}

    owned = db.execute(
        text(
            "SELECT 1 FROM sidequest_user_quests uq "
            "JOIN sidequest_users u ON u.id = uq.user_id "
            "WHERE uq.quest_id = :quest_id AND u.client_id = :client_id"
        ),
        {"quest_id": quest_id, "client_id": client_id},
    ).first()
    if owned is None:
        return {"error": "Quest not found."}

    record.status = feedback.status
    record.rating = feedback.rating
    record.reflection = feedback.reflection
    db.commit()
    db.refresh(record)
    _update_profile(db, client_id, record)

    return {
        "message": "Feedback saved. Your future sidequests will adapt.",
        "quest": _history_dict(record),
    }


@app.get("/profile")
def profile_endpoint(db: Session = Depends(get_db), client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID")):
    client_id = _client_id(client_header)
    return _profile_data(db, client_id)


@app.get("/stats")
def stats(
    db: Session = Depends(get_db),
    client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID"),
):
    client_id = _client_id(client_header)
    user = _ensure_user(db, client_id)

    owned_ids = db.execute(
        text("SELECT quest_id FROM sidequest_user_quests WHERE user_id = :user_id"),
        {"user_id": user["id"]},
    ).scalars().all()
    scoped_ids = list(owned_ids) or [-1]

    completed = (
        db.query(func.count(QuestHistory.id))
        .filter(QuestHistory.status == "completed")
        .filter(QuestHistory.id.in_(scoped_ids))
        .scalar()
        or 0
    )
    minutes = (
        db.query(func.coalesce(func.sum(QuestHistory.duration_minutes), 0))
        .filter(QuestHistory.status == "completed")
        .filter(QuestHistory.id.in_(scoped_ids))
        .scalar()
        or 0
    )
    categories = (
        db.query(QuestHistory.category)
        .filter(QuestHistory.status == "completed")
        .filter(QuestHistory.id.in_(scoped_ids))
        .distinct()
        .count()
    )

    return {
        "sidequests_completed": int(completed),
        "minutes_explored": int(minutes),
        "quests_attempted": len(owned_ids),
        "categories_explored": int(categories),
    }


@app.post("/chaos-quest")
async def chaos_quest(request: ChaosRequest, db: Session = Depends(get_db), client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID")):
    client_id = _client_id(client_header)
    try:
        candidates = await _generate_candidates(
            db,
            client_id,
            destination="somewhere nearby",
            time_available=request.time_available,
            mood="curious",
            interests=[],
            count=2,
            chaos=True,
        )

        if not candidates:
            return {"error": "Chaos needs another try. No safe quest was generated."}

        selected, selected_score = max(
            candidates,
            key=lambda item: item[1],
        )
        history = _save_quest(
            db,
            client_id,
            request_destination="Chaos Mode",
            time_available=request.time_available,
            mood="curious",
            interests=[],
            quest=selected,
        )

        return {
            "id": history.id,
            "mode": "chaos",
            "score": selected_score,
            "quest": selected.model_dump(),
        }

    except Exception as exc:
        print(
            f"SIDEQUEST chaos generation failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {"error": "Chaos quest generation failed. Please try again."}


@app.post("/check-repetition")
def check_quest_repetition(quest: Quest, db: Session = Depends(get_db), client_header: str | None = Header(default=None, alias="X-SIDEQUEST-CLIENT-ID")):
    client_id = _client_id(client_header)
    repeated = _is_repetitive(db, client_id, quest)
    return {
        "repeated": repeated,
        "safe_to_use": not repeated,
    }


@app.post("/check-safety")
def check_safety(quest: Quest):
    safe, blocked_phrase = _is_safe(quest)
    return {
        "safe": safe,
        "blocked_phrase": blocked_phrase,
    }
