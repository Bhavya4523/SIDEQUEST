import json

from backend.models import UserProfile


def get_or_create_profile(db):
    profile = db.query(UserProfile).first()

    if profile is None:
        profile = UserProfile(
            category_preferences="{}"
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


def update_profile(db, category, status, rating):
    profile = get_or_create_profile(db)

    preferences = json.loads(profile.category_preferences)

    current_score = preferences.get(category, 0.5)

    if status == "completed":
        change = 0.10

        if rating is not None:
            change += (rating - 3) * 0.05

    elif status == "partly":
        change = 0.02

    else:
        change = -0.10

    new_score = max(
        0.0,
        min(1.0, current_score + change)
    )

    preferences[category] = round(new_score, 3)

    profile.category_preferences = json.dumps(preferences)

    db.commit()
    db.refresh(profile)

    return profile