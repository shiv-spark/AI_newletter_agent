
from app.services.user_preferences import get_user_preferences
from app.services.research_pipeline import run_research_pipeline


def run_user_research(
    user_id: int,
    max_results_per_topic: int = 10,
) -> dict:
    """Run research using the topics saved for a specific user."""

    preferences = get_user_preferences(user_id)

    if preferences is None:
        raise ValueError("User not found.")

    if not preferences["is_active"]:
        return {
            "user_id": user_id,
            "status": "inactive",
            "message": "User is inactive. Research was not started.",
        }

    topics = preferences["topics"]

    if not topics:
        return {
            "user_id": user_id,
            "status": "no_topics",
            "message": "No topics saved for this user.",
        }

    research_result = run_research_pipeline(
        topics=topics,
        max_results_per_topic=max_results_per_topic,
    )

    return {
        "user_id": user_id,
        "email": preferences["email"],
        "language": preferences["language"],
        "frequency": preferences["frequency"],
        "status": "completed",
        **research_result,
    }
