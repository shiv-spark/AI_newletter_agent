"""Create (or reset) a test user whose newsletter is due in 2 minutes.

Run from the project folder:
    python create_test_user.py you@example.com
"""
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database.db import SessionLocal
from app.database.models import User
from app.services.user_preferences import (
    add_topic,
    create_user,
    get_user_preferences,
    update_schedule_preferences,
)

TOPIC = "AI"
TIMEZONE = "Asia/Kolkata"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python create_test_user.py you@example.com")
        return

    email = sys.argv[1].strip().lower()

    # Create the user, or reuse it if the email already exists.
    try:
        user_id = create_user(email)
        print(f"Created user {user_id}.")
    except Exception:
        with SessionLocal() as session:
            user_id = session.scalar(select(User.id).where(User.email == email))

        if user_id is None:
            raise

        print(f"User {user_id} already exists, reusing it.")

    try:
        add_topic(user_id, TOPIC)
    except ValueError:
        pass  # topic already added

    run_time = datetime.now(ZoneInfo(TIMEZONE)) + timedelta(minutes=2)
    update_schedule_preferences(
        user_id,
        preferred_time=run_time.strftime("%H:%M"),
        timezone=TIMEZONE,
    )

    # Clear "already ran today" so the scheduler can run this user again.
    with SessionLocal() as session:
        user = session.get(User, user_id)
        user.last_run_date = None
        session.commit()

    preferences = get_user_preferences(user_id)
    print(f"Email:          {preferences['email']}")
    print(f"Topics:         {preferences['topics']}")
    print(f"Preferred time: {preferences['preferred_time']} ({TIMEZONE})")
    print()
    print("Next: start Redis, then in two separate terminals run:")
    print("  celery -A app.celery_app worker --loglevel=info --pool=solo")
    print("  celery -A app.celery_app beat --loglevel=info")
    print("and wait until that time. Then run: python check_test_user.py", email)


if __name__ == "__main__":
    main()