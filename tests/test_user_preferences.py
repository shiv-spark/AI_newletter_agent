
import uuid

import pytest

from app.services.user_preferences import (
    add_topic,
    create_user,
    get_user_preferences,
    remove_topic,
    update_preferences,
    update_schedule_preferences,
)


def test_user_preferences_crud():
    email = f"newsletter-{uuid.uuid4().hex}@example.com"

    user_id = create_user(email)

    add_topic(user_id, "AI")
    add_topic(user_id, "Data Engineering")
    add_topic(user_id, "AI")

    preferences = get_user_preferences(user_id)

    assert preferences is not None
    assert preferences["email"] == email
    assert preferences["language"] == "en"
    assert preferences["frequency"] == "daily"
    assert sorted(preferences["topics"]) == [
        "AI",
        "Data Engineering",
    ]

    update_preferences(
        user_id,
        language="en",
        frequency="weekly",
    )

    updated = get_user_preferences(user_id)
    assert updated["frequency"] == "weekly"

    assert remove_topic(user_id, "AI") is True
    assert remove_topic(user_id, "AI") is False

    final_preferences = get_user_preferences(user_id)
    assert final_preferences["topics"] == ["Data Engineering"]


def test_unknown_user_returns_none():
    assert get_user_preferences(-1) is None


def test_invalid_frequency_is_rejected():
    email = f"newsletter-{uuid.uuid4().hex}@example.com"
    user_id = create_user(email)

    with pytest.raises(ValueError, match="Frequency"):
        update_preferences(user_id, "en", "hourly")


def test_new_user_gets_default_schedule():
    email = f"newsletter-{uuid.uuid4().hex}@example.com"
    user_id = create_user(email)

    preferences = get_user_preferences(user_id)

    assert preferences["preferred_time"] == "08:00"
    assert preferences["preferred_day"] is None
    assert preferences["timezone"] == "Asia/Kolkata"


def test_schedule_preferences_can_be_updated():
    email = f"newsletter-{uuid.uuid4().hex}@example.com"
    user_id = create_user(email, frequency="weekly")

    update_schedule_preferences(
        user_id,
        preferred_time="18:30",
        preferred_day="Friday",
        timezone="Europe/London",
    )

    preferences = get_user_preferences(user_id)

    assert preferences["preferred_time"] == "18:30"
    assert preferences["preferred_day"] == "friday"
    assert preferences["timezone"] == "Europe/London"


def test_schedule_update_keeps_values_that_are_not_given():
    email = f"newsletter-{uuid.uuid4().hex}@example.com"
    user_id = create_user(email)

    update_schedule_preferences(user_id, preferred_time="07:15")

    preferences = get_user_preferences(user_id)

    assert preferences["preferred_time"] == "07:15"
    assert preferences["timezone"] == "Asia/Kolkata"


def test_invalid_schedule_values_are_rejected():
    email = f"newsletter-{uuid.uuid4().hex}@example.com"
    user_id = create_user(email)

    with pytest.raises(ValueError, match="Time"):
        update_schedule_preferences(user_id, preferred_time="25:99")

    with pytest.raises(ValueError, match="Day"):
        update_schedule_preferences(user_id, preferred_day="someday")

    with pytest.raises(ValueError, match="Timezone"):
        update_schedule_preferences(user_id, timezone="Mars/Base")

    with pytest.raises(ValueError, match="User not found"):
        update_schedule_preferences(-1, preferred_time="08:00")
