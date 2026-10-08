import json

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.anti_repetition import check_repetition
from backend.candidate_service import generate_candidates
from backend.database import get_db
from backend.models import QuestHistory
from backend.ollama_service import generate_quest
from backend.personalization import (
    get_or_create_profile,
    update_profile,
)
from backend.quest_filter import validate_quest
from backend.ranking import rank_candidates
from backend.schemas import (
    ChaosRequest,
    Quest,
    QuestFeedback,
    QuestRequest,
)


app = FastAPI(
    title="SIDEQUEST API",
    description="Local-first AI sidequest generator",
    version="0.1.0",
)


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


@app.get("/")
def root():
    return {
        "message": "SIDEQUEST API is running",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "ai": "local",
        "model": "gemma3:4b",
        "offline_capable": True,
    }


@app.post("/generate-quest")
async def create_quest(
    request: QuestRequest,
    db: Session = Depends(get_db),
):
    profile = get_or_create_profile(db)

    profile_data = {
        "category_preferences": json.loads(
            profile.category_preferences
        ),
        "preferred_duration": profile.preferred_duration,
        "preferred_difficulty": profile.preferred_difficulty,
        "novelty_preference": profile.novelty_preference,
    }

    prompt = f"""
Create a SIDEQUEST for the user.

Destination: {request.destination}
Time available: {request.time_available} minutes
Mood: {request.mood}
Interests: {
    ", ".join(request.interests)
    if request.interests
    else "none provided"
}

The quest should feel like a small spontaneous adventure
that fits naturally into the user's journey.
"""

    try:
        candidates = await generate_candidates(
            prompt,
            count=3,
        )

        if not candidates:
            return {
                "error": (
                    "Could not generate a safe and sufficiently "
                    "different quest."
                )
            }

        repetition_results = [
            check_repetition(
                db=db,
                title=quest.title,
                objective=quest.objective,
                steps=quest.steps,
                category=quest.category,
            )
            for quest in candidates
        ]

        ranked = rank_candidates(
            candidates=candidates,
            request=request,
            profile=profile_data,
            repetition_results=repetition_results,
        )

        if not ranked:
            return {
                "error": (
                    "All generated quests were too repetitive. "
                    "Please try again."
                )
            }

        selected = ranked[0]["quest"]
        selected_score = ranked[0]["score"]

        history = QuestHistory(
            destination=request.destination,
            time_available=request.time_available,
            mood=request.mood,
            interests=json.dumps(request.interests),
            title=selected.title,
            duration_minutes=selected.duration_minutes,
            difficulty=selected.difficulty,
            category=selected.category,
            objective=selected.objective,
            steps=json.dumps(selected.steps),
            novelty_score=selected.novelty_score,
            safety_notes=json.dumps(selected.safety_notes),
            status="generated",
        )

        db.add(history)
        db.commit()
        db.refresh(history)

        return {
            "id": history.id,
            "score": selected_score,
            "quest": selected.model_dump(),
        }

    except Exception:
        return {
            "error": (
                "Local AI is unavailable right now. "
                "Make sure Ollama is running and try again."
            )
        }


@app.post("/generate-candidates")
async def create_candidates(
    request: QuestRequest,
    db: Session = Depends(get_db),
):
    profile = get_or_create_profile(db)

    profile_data = {
        "category_preferences": json.loads(
            profile.category_preferences
        ),
        "preferred_duration": profile.preferred_duration,
        "preferred_difficulty": profile.preferred_difficulty,
        "novelty_preference": profile.novelty_preference,
    }

    prompt = f"""
Create a SIDEQUEST for the user.

Destination: {request.destination}
Time available: {request.time_available} minutes
Mood: {request.mood}
Interests: {
    ", ".join(request.interests)
    if request.interests
    else "none provided"
}

The quest should:
- fit within the available time
- encourage real-world exploration
- match the mood
- use interests when appropriate
- remain safe and practical
"""

    try:
        candidates = await generate_candidates(
            prompt,
            count=3,
        )

        repetition_results = [
            check_repetition(
                db=db,
                title=quest.title,
                objective=quest.objective,
                steps=quest.steps,
                category=quest.category,
            )
            for quest in candidates
        ]

        ranked = rank_candidates(
            candidates=candidates,
            request=request,
            profile=profile_data,
            repetition_results=repetition_results,
        )

        return {
            "candidate_count": len(candidates),
            "valid_candidate_count": len(ranked),
            "candidates": [
                {
                    "score": item["score"],
                    "quest": item["quest"].model_dump(),
                }
                for item in ranked
            ],
        }

    except Exception:
        return {
            "error": "Could not generate local AI candidates."
        }


@app.get("/quests")
def get_quests(
    db: Session = Depends(get_db),
):
    quests = (
        db.query(QuestHistory)
        .order_by(QuestHistory.created_at.desc())
        .all()
    )

    return [
        {
            "id": quest.id,
            "destination": quest.destination,
            "time_available": quest.time_available,
            "mood": quest.mood,
            "interests": json.loads(quest.interests),
            "title": quest.title,
            "duration_minutes": quest.duration_minutes,
            "difficulty": quest.difficulty,
            "category": quest.category,
            "objective": quest.objective,
            "steps": json.loads(quest.steps),
            "novelty_score": quest.novelty_score,
            "safety_notes": json.loads(quest.safety_notes),
            "status": quest.status,
            "rating": quest.rating,
            "reflection": quest.reflection,
            "created_at": quest.created_at.isoformat(),
        }
        for quest in quests
    ]


@app.post("/quests/{quest_id}/feedback")
def submit_feedback(
    quest_id: int,
    feedback: QuestFeedback,
    db: Session = Depends(get_db),
):
    quest = (
        db.query(QuestHistory)
        .filter(QuestHistory.id == quest_id)
        .first()
    )

    if quest is None:
        return {
            "error": "Quest not found"
        }

    quest.status = feedback.status
    quest.rating = feedback.rating
    quest.reflection = feedback.reflection

    update_profile(
        db=db,
        category=quest.category,
        status=feedback.status,
        rating=feedback.rating,
    )

    db.commit()
    db.refresh(quest)

    return {
        "message": "Feedback saved",
        "id": quest.id,
        "status": quest.status,
        "rating": quest.rating,
        "reflection": quest.reflection,
    }


@app.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
):
    profile = get_or_create_profile(db)

    return {
        "category_preferences": json.loads(
            profile.category_preferences
        ),
        "preferred_duration": profile.preferred_duration,
        "preferred_difficulty": profile.preferred_difficulty,
        "novelty_preference": profile.novelty_preference,
    }


@app.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
):
    quests = (
        db.query(QuestHistory)
        .order_by(QuestHistory.created_at.desc())
        .all()
    )

    completed_quests = [
        quest
        for quest in quests
        if quest.status == "completed"
    ]

    minutes_explored = sum(
        quest.duration_minutes
        for quest in completed_quests
    )

    categories = {
        quest.category
        for quest in quests
    }

    return {
        "sidequests_completed": len(completed_quests),
        "minutes_explored": minutes_explored,
        "quests_attempted": len(quests),
        "categories_explored": len(categories),
    }


@app.post("/chaos-quest")
async def create_chaos_quest(
    request: ChaosRequest,
    db: Session = Depends(get_db),
):
    profile = get_or_create_profile(db)

    profile_data = {
        "category_preferences": json.loads(
            profile.category_preferences
        ),
        "preferred_duration": profile.preferred_duration,
        "preferred_difficulty": profile.preferred_difficulty,
        "novelty_preference": profile.novelty_preference,
    }

    prompt = f"""
Create a spontaneous SIDEQUEST.

The user has exactly {request.time_available} minutes.

This is CHAOS MODE.

The user does not provide a destination,
mood, or interest.

Create an unexpected but safe real-world adventure.

Requirements:
- fit within {request.time_available} minutes
- encourage exploration and curiosity
- be meaningfully different from ordinary routine
- do not require phone usage
- do not require online research
- stay in public and safe areas
- do not involve wildlife or dangerous activities
- keep the quest realistic and simple
"""

    try:
        candidates = await generate_candidates(
            prompt,
            count=2,
        )

        if not candidates:
            return {
                "error": "Could not generate a safe chaos quest."
            }

        repetition_results = [
            check_repetition(
                db=db,
                title=quest.title,
                objective=quest.objective,
                steps=quest.steps,
                category=quest.category,
            )
            for quest in candidates
        ]

        chaos_request = QuestRequest(
            destination="Chaos Mode",
            time_available=request.time_available,
            mood="spontaneous",
            interests=[],
        )

        ranked = rank_candidates(
            candidates=candidates,
            request=chaos_request,
            profile=profile_data,
            repetition_results=repetition_results,
        )

        if not ranked:
            return {
                "error": (
                    "All chaos quests were rejected as repetitive."
                )
            }

        selected = ranked[0]["quest"]
        selected_score = ranked[0]["score"]

        history = QuestHistory(
            destination="Chaos Mode",
            time_available=request.time_available,
            mood="spontaneous",
            interests=json.dumps([]),
            title=selected.title,
            duration_minutes=selected.duration_minutes,
            difficulty=selected.difficulty,
            category=selected.category,
            objective=selected.objective,
            steps=json.dumps(selected.steps),
            novelty_score=selected.novelty_score,
            safety_notes=json.dumps(selected.safety_notes),
            status="generated",
        )

        db.add(history)
        db.commit()
        db.refresh(history)

        return {
            "id": history.id,
            "mode": "chaos",
            "score": selected_score,
            "quest": selected.model_dump(),
        }

    except Exception:
        return {
            "error": (
                "Local AI is unavailable right now. "
                "Make sure Ollama is running and try again."
            )
        }


@app.post("/check-repetition")
def check_quest_repetition(
    quest: Quest,
    db: Session = Depends(get_db),
):
    return check_repetition(
        db=db,
        title=quest.title,
        objective=quest.objective,
        steps=quest.steps,
        category=quest.category,
    )


@app.post("/check-safety")
def check_quest_safety(quest: Quest):
    return validate_quest(quest)