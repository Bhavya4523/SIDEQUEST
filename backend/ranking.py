def calculate_score(
    quest,
    request,
    profile,
    category_repeated: bool,
):
    # 1. Time fit: 25%
    if quest.duration_minutes <= request.time_available:
        time_score = 1.0
    else:
        time_score = max(
            0.0,
            1.0 - (
                (quest.duration_minutes - request.time_available)
                / request.time_available
            ),
        )

    # 2. Preference match: 20%
    preferences = profile.get("category_preferences", {})
    preference_score = preferences.get(
        quest.category,
        0.5,
    )

    # 3. Novelty: 20%
    novelty_score = quest.novelty_score

    # 4. Feasibility: 15%
    feasibility_score = (
        1.0
        if quest.duration_minutes <= request.time_available
        else 0.0
    )

    # 5. Route compatibility: 10%
    # For MVP, destination presence gives us a neutral score.
    route_score = 1.0 if request.destination else 0.0

    # 6. Historical success: 10%
    historical_score = preference_score

    # Penalize recent category repetition.
    repetition_penalty = 0.15 if category_repeated else 0.0

    final_score = (
        0.25 * time_score
        + 0.20 * preference_score
        + 0.20 * novelty_score
        + 0.15 * feasibility_score
        + 0.10 * route_score
        + 0.10 * historical_score
        - repetition_penalty
    )

    return round(
        max(0.0, min(1.0, final_score)),
        3,
    )


def rank_candidates(
    candidates,
    request,
    profile,
    repetition_results,
):
    ranked = []

    for quest, repetition in zip(
        candidates,
        repetition_results,
    ):
        if not repetition["allowed"]:
            continue

        score = calculate_score(
            quest=quest,
            request=request,
            profile=profile,
            category_repeated=repetition["category_repeated"],
        )

        ranked.append({
            "quest": quest,
            "score": score,
        })

    ranked.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return ranked