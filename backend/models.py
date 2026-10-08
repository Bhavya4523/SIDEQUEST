from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from backend.database import Base


class QuestHistory(Base):
    __tablename__ = "quest_history"

    id = Column(Integer, primary_key=True, index=True)

    destination = Column(String(255), nullable=False)
    time_available = Column(Integer, nullable=False)
    mood = Column(String(100), nullable=False)
    interests = Column(Text, nullable=False, default="[]")

    title = Column(String(255), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    difficulty = Column(String(50), nullable=False)
    category = Column(String(100), nullable=False)
    objective = Column(Text, nullable=False)
    steps = Column(Text, nullable=False)
    novelty_score = Column(Float, nullable=False)

    safety_notes = Column(Text, nullable=False)

    status = Column(String(50), nullable=False, default="generated")
    rating = Column(Integer, nullable=True)
    reflection = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True)

    category_preferences = Column(
        Text,
        nullable=False,
        default="{}",
    )

    preferred_duration = Column(
        Integer,
        nullable=False,
        default=20,
    )

    preferred_difficulty = Column(
        String(50),
        nullable=False,
        default="easy",
    )

    novelty_preference = Column(
        Float,
        nullable=False,
        default=0.7,
    )