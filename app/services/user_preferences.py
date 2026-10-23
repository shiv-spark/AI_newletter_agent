from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.db import SessionLocal
from app.database.models import User, UserTopic

VALID_DAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


def parse_time(value) -> time:
    """Accept a time object or an HH:MM text such as 08:30."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)

    try:
        return datetime.strptime(str(value).strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(
            "Time must be in HH:MM format, for example 08:30."
        ) from exc


def create_user(
    email: str,
    language: str = "en",
    frequency: str = "daily",
) -> int:
    email = email.strip().lower()

    if not email:
        raise ValueError("Email cannot be empty.")

    if frequency not in {"daily", "weekly"}:
        raise ValueError("Frequency must be daily or weekly.")

    with SessionLocal() as session:
        user = User(
            email=email,
            language=language,
            frequency=frequency,
        )
        session.add(user)

        try:
            session.commit()
            session.refresh(user)
            return user.id
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(
                "User email already exists or the data is invalid."
            ) from exc


def add_topic(user_id: int, topic: str) -> None:
    topic = topic.strip()

    if not topic:
        raise ValueError("Topic cannot be empty.")

    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            raise ValueError("User not found.")

        existing = session.scalar(
            select(UserTopic).where(
                UserTopic.user_id == user_id,
                UserTopic.topic == topic,
            )
        )

        if existing is not None:
            return

        session.add(UserTopic(user_id=user_id, topic=topic))
        session.commit()


def get_user_preferences(user_id: int) -> dict | None:
    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            return None

        topics = session.scalars(
            select(UserTopic.topic)
            .where(UserTopic.user_id == user_id)
            .order_by(UserTopic.topic)
        ).all()

        return {
            "id": user.id,
            "email": user.email,
            "language": user.language,
            "frequency": user.frequency,
            "is_active": user.is_active,
            "preferred_time": user.preferred_time.strftime("%H:%M"),
            "preferred_day": user.preferred_day,
            "timezone": user.timezone,
            "topics": list(topics),
        }


def update_preferences(
    user_id: int,
    language: str,
    frequency: str,
) -> None:
    if frequency not in {"daily", "weekly"}:
        raise ValueError("Frequency must be daily or weekly.")

    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            raise ValueError("User not found.")

        user.language = language
        user.frequency = frequency
        session.commit()


def update_schedule_preferences(
    user_id: int,
    preferred_time: str | time | None = None,
    preferred_day: str | None = None,
    timezone: str | None = None,
) -> None:
    """Update only the schedule values that are provided.

    None means "keep the current value".
    """
    if preferred_time is not None:
        preferred_time = parse_time(preferred_time)

    if preferred_day is not None:
        preferred_day = preferred_day.strip().lower()

        if preferred_day not in VALID_DAYS:
            raise ValueError(
                "Day must be a weekday name, for example monday."
            )

    if timezone is not None:
        timezone = timezone.strip()

        try:
            ZoneInfo(timezone)
        except Exception as exc:
            raise ValueError(
                "Timezone is not valid, for example Asia/Kolkata."
            ) from exc

    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            raise ValueError("User not found.")

        if preferred_time is not None:
            user.preferred_time = preferred_time

        if preferred_day is not None:
            user.preferred_day = preferred_day

        if timezone is not None:
            user.timezone = timezone

        session.commit()


def remove_topic(user_id: int, topic: str) -> bool:
    with SessionLocal() as session:
        topic_record = session.scalar(
            select(UserTopic).where(
                UserTopic.user_id == user_id,
                UserTopic.topic == topic.strip(),
            )
        )

        if topic_record is None:
            return False

        session.delete(topic_record)
        session.commit()
        return True
