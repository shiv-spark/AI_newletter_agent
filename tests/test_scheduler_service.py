import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import delete

from app.database.db import SessionLocal
from app.database.models import User

from app.services import scheduler_service


def make_user(**overrides):
    values = {
        "frequency": "daily",
        "preferred_time": time(8, 0),
        "preferred_day": None,
        "timezone": "Asia/Kolkata",
        "last_run_date": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# 04:00 UTC on Friday 2026-10-23 is 09:30 in Asia/Kolkata.
FRIDAY_MORNING = datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)


def test_daily_user_is_due_after_preferred_time():
    assert scheduler_service.is_user_due(make_user(), FRIDAY_MORNING) is True


def test_user_is_not_due_before_preferred_time():
    user = make_user(preferred_time=time(10, 0))

    assert scheduler_service.is_user_due(user, FRIDAY_MORNING) is False


def test_user_is_not_due_if_already_ran_today():
    user = make_user(last_run_date=date(2026, 10, 23))

    assert scheduler_service.is_user_due(user, FRIDAY_MORNING) is False


def test_user_timezone_is_used_for_the_day_and_time():
    # 20:00 UTC on Thursday is already 01:30 Friday in Asia/Kolkata.
    thursday_night = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)
    user = make_user(
        frequency="weekly",
        preferred_day="friday",
        preferred_time=time(1, 0),
    )

    assert scheduler_service.is_user_due(user, thursday_night) is True

    london_user = make_user(
        frequency="weekly",
        preferred_day="friday",
        preferred_time=time(1, 0),
        timezone="Europe/London",
    )

    assert scheduler_service.is_user_due(london_user, thursday_night) is False


def test_weekly_user_is_due_only_on_preferred_day():
    friday_user = make_user(frequency="weekly", preferred_day="friday")
    monday_user = make_user(frequency="weekly", preferred_day="monday")

    assert scheduler_service.is_user_due(friday_user, FRIDAY_MORNING) is True
    assert scheduler_service.is_user_due(monday_user, FRIDAY_MORNING) is False


def test_weekly_user_without_day_defaults_to_monday():
    user = make_user(frequency="weekly", preferred_day=None)

    assert scheduler_service.is_user_due(user, FRIDAY_MORNING) is False


def test_run_for_user_approves_without_sending_when_sending_is_off():
    with (
        patch.object(scheduler_service, "run_user_research") as research,
        patch.object(
            scheduler_service,
            "generate_editorial_issue",
            return_value={"status": "approved", "issue_id": 7},
        ),
        patch.object(scheduler_service, "send_newsletter") as send,
    ):
        status = scheduler_service.run_newsletter_for_user(1, False)

    research.assert_called_once_with(1)
    send.assert_not_called()
    assert status == "approved"


def test_run_for_user_sends_when_sending_is_on():
    with (
        patch.object(scheduler_service, "run_user_research"),
        patch.object(
            scheduler_service,
            "generate_editorial_issue",
            return_value={"status": "approved", "issue_id": 7},
        ),
        patch.object(
            scheduler_service,
            "send_newsletter",
            return_value={"status": "sent"},
        ) as send,
    ):
        status = scheduler_service.run_newsletter_for_user(1, True)

    send.assert_called_once_with(7)
    assert status == "sent"


def test_run_for_user_does_not_send_when_the_issue_is_not_approved():
    with (
        patch.object(scheduler_service, "run_user_research"),
        patch.object(
            scheduler_service,
            "generate_editorial_issue",
            return_value={"status": "no_new_articles"},
        ),
        patch.object(scheduler_service, "send_newsletter") as send,
    ):
        status = scheduler_service.run_newsletter_for_user(1, True)

    send.assert_not_called()
    assert status == "no_new_articles"


def test_scheduled_run_marks_user_and_runs_only_due_users():
    with SessionLocal() as session:
        user = User(email=f"sched-{uuid.uuid4().hex}@example.com")
        session.add(user)
        session.commit()
        user_id = user.id

    try:
        with (
            patch.object(
                scheduler_service,
                "is_user_due",
                side_effect=lambda user, now: user.id == user_id,
            ),
            patch.object(
                scheduler_service,
                "run_newsletter_for_user",
                return_value="sent",
            ) as run,
            patch.object(scheduler_service.settings, "scheduler_send_enabled", False),
        ):
            scheduler_service.scheduled_newsletter_run()

        run.assert_called_once_with(user_id, False)

        with SessionLocal() as session:
            saved_user = session.get(User, user_id)
            assert saved_user.last_run_date is not None

    finally:
        with SessionLocal() as session:
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def test_one_failing_user_does_not_stop_the_scheduled_run():
    with SessionLocal() as session:
        first = User(email=f"sched-{uuid.uuid4().hex}@example.com")
        second = User(email=f"sched-{uuid.uuid4().hex}@example.com")
        session.add_all([first, second])
        session.commit()
        ids = [first.id, second.id]

    def fake_run(user_id, send_emails):
        if user_id == ids[0]:
            raise RuntimeError("boom")
        return "sent"

    try:
        with (
            patch.object(
                scheduler_service,
                "is_user_due",
                side_effect=lambda user, now: user.id in ids,
            ),
            patch.object(
                scheduler_service,
                "run_newsletter_for_user",
                side_effect=fake_run,
            ) as run,
        ):
            scheduler_service.scheduled_newsletter_run()

        called_ids = [call.args[0] for call in run.call_args_list]
        assert sorted(called_ids) == sorted(ids)

    finally:
        with SessionLocal() as session:
            session.execute(delete(User).where(User.id.in_(ids)))
            session.commit()


def test_issue_that_needs_review_is_never_sent():
    with (
        patch.object(scheduler_service, "run_user_research"),
        patch.object(
            scheduler_service,
            "generate_editorial_issue",
            return_value={"status": "needs_review", "issue_id": 7},
        ),
        patch.object(scheduler_service, "send_newsletter") as send,
    ):
        status = scheduler_service.run_newsletter_for_user(1, True)

    send.assert_not_called()
    assert status == "needs_review"


def test_failed_dispatch_does_not_mark_the_user_as_done_today():
    with SessionLocal() as session:
        user = User(email=f"sched-{uuid.uuid4().hex}@example.com")
        session.add(user)
        session.commit()
        user_id = user.id

    try:
        with (
            patch.object(
                scheduler_service,
                "is_user_due",
                side_effect=lambda user, now: user.id == user_id,
            ),
            patch.object(
                scheduler_service.run_newsletter_for_user_task,
                "delay",
                side_effect=ConnectionError("redis down"),
            ),
        ):
            scheduler_service.scheduled_newsletter_run()

        with SessionLocal() as session:
            assert session.get(User, user_id).last_run_date is None

    finally:
        with SessionLocal() as session:
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


def test_task_reraises_so_failures_are_visible():
    import pytest

    with patch.object(
        scheduler_service, "run_newsletter_for_user", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            scheduler_service.run_newsletter_for_user_task(1, True)
