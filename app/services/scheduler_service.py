import logging
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database.db import SessionLocal
from app.database.models import User
from app.services.delivery_service import send_newsletter
from app.services.editorial_service import generate_editorial_issue
from app.services.user_research import run_user_research
from app.celery_app import celery_app



logger = logging.getLogger(__name__)


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
    """Research, run the editorial pipeline and (optionally) send.

    Only an issue the Editor approved is ever sent. Returns a status.
    """
    run_user_research(user_id)

    issue = generate_editorial_issue(user_id)

    if issue["status"] != "approved":
        logger.warning(
            "Newsletter for user %s stopped with status %s. Reason: %s",
            user_id,
            issue["status"],
            issue.get("error") or issue.get("note") or issue.get("found") or "n/a",
        )
        return issue["status"]

    if not send_emails:
        return "approved"

    return send_newsletter(issue["issue_id"])["status"]



# 1. Individual newsletter job (runs across Celery workers)
@celery_app.task(name="generate_newsletter_task")
def run_newsletter_for_user_task(user_id: int, send_emails: bool):
    logger.info(
        "Starting newsletter pipeline for user %s (send_emails=%s)...",
        user_id,
        send_emails,
    )
    try:
        status = run_newsletter_for_user(user_id, send_emails)
        logger.info("Newsletter pipeline finished for user %s: %s", user_id, status)

        expected = "sent" if send_emails else "approved"
        if status not in (expected, "sent"):
            logger.warning(
                "Newsletter for user %s was NOT delivered. Result: %s",
                user_id,
                status,
            )
        elif not send_emails:
            logger.warning(
                "Newsletter for user %s was approved but NOT emailed, because "
                "SCHEDULER_SEND_ENABLED is false in .env.",
                user_id,
            )

        return status
    except Exception:
        logger.exception("Newsletter run failed for user %s", user_id)
        raise


# 2. Celery Beat periodic dispatcher
@celery_app.task(name="app.services.scheduler_service.scheduled_newsletter_run")
def scheduled_newsletter_run() -> None:
    """Find users who are due and push them as tasks to Celery."""
    now = datetime.now(dt_timezone.utc)

    with SessionLocal() as session:
        users = session.scalars(
            select(User).where(User.is_active.is_(True))
        ).all()

        for user in users:
            user_id = user.id

            try:
                if not is_user_due(user, now):
                    continue

                logger.info("User %s is due for scheduled newsletter run.", user_id)

                # Dispatch first. The user is marked as done for today only
                # after the task was queued, so a Redis or worker problem
                # does not lock the user out until tomorrow.
                run_newsletter_for_user_task.delay(
                    user_id, settings.scheduler_send_enabled
                )

                user.last_run_date = get_local_now(user, now).date()
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Could not schedule newsletter for user %s", user_id)
