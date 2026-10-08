from backend.database import Base, engine
from backend.models import QuestHistory


Base.metadata.create_all(bind=engine)

print("DATABASE TABLES CREATED")