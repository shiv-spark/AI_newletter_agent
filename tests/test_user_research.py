
import pytest

from app.services.user_research import run_user_research


def test_user_research_uses_saved_topics(monkeypatch):
    preferences = {
        "id": 101,
        "email": "user@example.com",
        "language": "en",
        "frequency": "daily",
        "is_active": True,
        "topics": ["AI", "Data Engineering"],
    }

    def fake_get_preferences(user_id):
        assert user_id == 101
        return preferences

    def fake_research_pipeline(topics, max_results_per_topic):
        assert topics == ["AI", "Data Engineering"]
        assert max_results_per_topic == 5

        return {
            "topics_requested": 2,
            "articles_collected": 10,
            "articles_after_batch_deduplication": 9,
            "inserted": 9,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
        }

    monkeypatch.setattr(
        "app.services.user_research.get_user_preferences",
        fake_get_preferences,
    )
    monkeypatch.setattr(
        "app.services.user_research.run_research_pipeline",
        fake_research_pipeline,
    )

    result = run_user_research(101, max_results_per_topic=5)

    assert result["status"] == "completed"
    assert result["email"] == "user@example.com"
    assert result["topics_requested"] == 2
    assert result["inserted"] == 9


def test_user_research_rejects_unknown_user(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_research.get_user_preferences",
        lambda user_id: None,
    )

    with pytest.raises(ValueError, match="User not found"):
        run_user_research(99999)


def test_inactive_user_does_not_start_research(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_research.get_user_preferences",
        lambda user_id: {
            "id": user_id,
            "email": "inactive@example.com",
            "language": "en",
            "frequency": "daily",
            "is_active": False,
            "topics": ["AI"],
        },
    )

    def should_not_run(*args, **kwargs):
        pytest.fail("Research should not run for inactive users.")

    monkeypatch.setattr(
        "app.services.user_research.run_research_pipeline",
        should_not_run,
    )

    result = run_user_research(101)

    assert result["status"] == "inactive"


def test_user_without_topics_does_not_start_research(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_research.get_user_preferences",
        lambda user_id: {
            "id": user_id,
            "email": "user@example.com",
            "language": "en",
            "frequency": "daily",
            "is_active": True,
            "topics": [],
        },
    )

    def should_not_run(*args, **kwargs):
        pytest.fail("Research should not run without topics.")

    monkeypatch.setattr(
        "app.services.user_research.run_research_pipeline",
        should_not_run,
    )

    result = run_user_research(101)

    assert result["status"] == "no_topics"
