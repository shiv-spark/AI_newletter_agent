import logging
from collections import Counter
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import settings
from app.database.db import SessionLocal
from app.database.models import User
from app.services.delivery_service import send_newsletter
from app.services.newsletter_service import generate_newsletter_draft
from app.services.user_research import run_user_research

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def scheduled_newsletter_check() -> None:
    """Inspect active users and their newsletter frequencies safely."""
    session = SessionLocal()

    try:
        statement = select(User).where(User.is_active.is_(True))
        active_users = session.scalars(statement).all()

        frequency_counts = Counter(
            user.frequency for user in active_users
        )

        logger.info(
            "Newsletter schedule check completed. "
            "Active users: %s, daily: %s, weekly: %s, "
            "other frequencies: %s. "
            "Safe mode is active; no newsletter was generated or sent.",
            len(active_users),
            frequency_counts.get("daily", 0),
            frequency_counts.get("weekly", 0),
            {
                frequency: count
                for frequency, count in frequency_counts.items()
                if frequency not in ("daily", "weekly")
            },
        )

    except Exception:
        logger.exception(
            "Newsletter schedule check failed. "
            "No newsletter was generated or sent."
        )

    finally:
        session.close()


def get_local_now(user, now: datetime | None = None) -> datetime:
    """Current time in the user's own timezone."""
    now = now or datetime.now(dt_timezone.utc)
    return now.astimezone(ZoneInfo(user.timezone))


def is_user_due(user, now: datetime | None = None) -> bool:
    """True if this user should get a newsletter run right now."""
    local_now = get_local_now(user, now)

    # Already ran today (in the user's timezone).
    if user.last_run_date == local_now.date():
        return False

    # The preferred time has not arrived yet.
    if local_now.time() < user.preferred_time:
        return False

    # Weekly users only run on their preferred day.
    if user.frequency == "weekly":
        preferred_day = user.preferred_day or "monday"

        if local_now.strftime("%A").lower() != preferred_day:
            return False

    return True


def run_newsletter_for_user(user_id: int, send_emails: bool) -> str:
    """Research, write a draft and (optionally) send it. Returns a status."""
    run_user_research(user_id)

    draft = generate_newsletter_draft(user_id)

    if draft["status"] != "draft_created":
        return draft["status"]

    if not send_emails:
        return "draft_created"

    return send_newsletter(draft["issue_id"])["status"]


def scheduled_newsletter_run() -> None:
    """Find users who are due and run the newsletter pipeline for them."""
    now = datetime.now(dt_timezone.utc)
    due_user_ids = []

    with SessionLocal() as session:
        users = session.scalars(
            select(User).where(User.is_active.is_(True))
        ).all()

        for user in users:
            try:
                if is_user_due(user, now):
                    # Mark first, so a crash cannot repeat the run every minute.
                    user.last_run_date = get_local_now(user, now).date()
                    due_user_ids.append(user.id)
            except Exception:
                logger.exception(
                    "Could not check the schedule for user %s", user.id
                )

        session.commit()

    for user_id in due_user_ids:
        try:
            status = run_newsletter_for_user(
                user_id, settings.scheduler_send_enabled
            )
            logger.info("Newsletter run for user %s: %s", user_id, status)
        except Exception:
            logger.exception("Newsletter run failed for user %s", user_id)


def start_scheduler() -> None:
    """Start the scheduler once. The automatic run is off unless enabled."""
    if scheduler.running:
        logger.info("Newsletter scheduler is already running.")
        return

    scheduler.add_job(
        scheduled_newsletter_check,
        trigger="interval",
        minutes=1,
        id="newsletter_safe_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    if settings.scheduler_enabled:
        scheduler.add_job(
            scheduled_newsletter_run,
            trigger="interval",
            minutes=1,
            id="newsletter_auto_run",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Automatic newsletter run is ON. Emails will be sent: %s",
            settings.scheduler_send_enabled,
        )
    else:
        logger.info("Automatic newsletter run is OFF.")

    scheduler.start()
    logger.info("Newsletter scheduler started.")


def stop_scheduler() -> None:
    """Stop the scheduler if it is running."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Newsletter scheduler stopped.")
