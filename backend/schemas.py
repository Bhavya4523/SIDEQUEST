from pydantic import BaseModel, Field
from typing import List, Literal


class Quest(BaseModel):
    title: str
    duration_minutes: int = Field(gt=0)
    difficulty: str
    category: str
    objective: str
    steps: List[str] = Field(min_length=1)
    novelty_score: float = Field(ge=0.0, le=1.0)
    safety_notes: List[str] = Field(min_length=1)


class QuestRequest(BaseModel):
    destination: str = Field(min_length=1)
    time_available: int = Field(gt=0)
    mood: str = Field(min_length=1)
    interests: List[str] = Field(default_factory=list)
    
class QuestFeedback(BaseModel):
    status: Literal["completed", "partly", "skipped"]
    rating: int | None = Field(default=None, ge=1, le=5)
    reflection: str | None = None

class ChaosRequest(BaseModel):
    time_available: int = Field(gt=0)