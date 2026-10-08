BLOCKED_PHRASES = [
    "use your phone",
    "using your phone",
    "take a photo",
    "take photos",
    "photograph",
    "google maps",
    "research online",
    "look it up online",
    "research the history",
    "enter private property",
    "trespass",
    "dangerous climbing",
    "climb a building",
    "approach wildlife",
    "follow wildlife",
    "follow an animal",
    "animal trail",
    "animal tracks",
    "disturb wildlife",
    "disturb animals",
    "disturb their habitat",
    "create a trail",
    "feed animals",
    "touch wildlife",
    "unsafe road",
    "cross a busy road",
    "illegal activity",
]

def validate_quest(quest):
    text = " ".join(
        [
            quest.title,
            quest.objective,
            *quest.steps,
            *quest.safety_notes,
        ]
    ).lower()

    matched = [
        phrase
        for phrase in BLOCKED_PHRASES
        if phrase in text
    ]

    return {
        "allowed": len(matched) == 0,
        "blocked_phrases": matched,
    }