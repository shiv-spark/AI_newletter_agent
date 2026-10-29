import pytest
from sqlalchemy import text

from app.database.db import engine
from app.services.topic_matching import build_topic_pattern


def matches(topic: str, value: str) -> bool:
    """Ask PostgreSQL itself, exactly like the real query does."""
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT :value ~* :pattern"),
                {"value": value, "pattern": build_topic_pattern(topic)},
            ).scalar()
        )


def test_short_topic_matches_whole_word_only():
    assert matches("AI", "New AI model released")
    assert matches("AI", "ai, explained")
    assert not matches("AI", "Spain said it would maintain the plan")


def test_multi_word_topic_ignores_extra_spaces_and_case():
    assert matches("Data Engineering", "Trends in data   engineering today")
    assert not matches("Data Engineering", "Engineering of data")


def test_special_characters_are_treated_as_normal_text():
    assert matches("C++", "Why C++ is still used")
    assert matches("Node.js", "Node.js 24 released")
    assert not matches("Node.js", "Nodexjs is not a thing")


def test_hindi_topic_matches():
    assert matches("क्रिकेट", "भारत ने क्रिकेट मैच जीता")


def test_empty_topic_is_rejected():
    with pytest.raises(ValueError, match="Topic"):
        build_topic_pattern("   ")
