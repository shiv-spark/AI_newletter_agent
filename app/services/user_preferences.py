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


class UserNotFound(ValueError):
    """The user id does not exist."""


class UserAlreadyExists(ValueError):
    """The email address is already registered."""


MAX_TOPICS = 20
MAX_TOPIC_LENGTH = 100  # the database column is String(100)


def validate_schedule_values(
    preferred_time=None,
    preferred_day: str | None = None,
    timezone: str | None = None,
) -> tuple:
    """Check schedule values and return them cleaned up.

    None means "not given" and stays None. Raises ValueError otherwise.
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

    return preferred_time, preferred_day, timezone


def clean_topics(topics) -> list[str]:
    """Trim topics, drop blanks and case-insensitive duplicates."""
    cleaned, seen = [], set()

    for topic in topics:
        topic = " ".join(str(topic).split())

        if not topic or topic.lower() in seen:
            continue

        if len(topic) > MAX_TOPIC_LENGTH:
            raise ValueError(
                f"A topic can have at most {MAX_TOPIC_LENGTH} characters."
            )

        seen.add(topic.lower())
        cleaned.append(topic)

    if len(cleaned) > MAX_TOPICS:
        raise ValueError(f"At most {MAX_TOPICS} topics are allowed.")

    return cleaned


def register_user(
    email: str,
    topics=(),
    language: str = "en",
    frequency: str = "daily",
    preferred_time=None,
    preferred_day: str | None = None,
    timezone: str | None = None,
) -> int:
    """Create a user with topics and schedule in one step.

    Everything is checked first and saved in one transaction, so invalid
    input never leaves a half-created user behind.
    """
    email = email.strip().lower()

    if not email:
        raise ValueError("Email cannot be empty.")

    if frequency not in {"daily", "weekly"}:
        raise ValueError("Frequency must be daily or weekly.")

    preferred_time, preferred_day, timezone = validate_schedule_values(
        preferred_time, preferred_day, timezone
    )
    topic_list = clean_topics(topics)

    with SessionLocal() as session:
        user = User(email=email, language=language, frequency=frequency)

        if preferred_time is not None:
            user.preferred_time = preferred_time

        if preferred_day is not None:
            user.preferred_day = preferred_day

        if timezone is not None:
            user.timezone = timezone

        session.add(user)

        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise UserAlreadyExists(
                "A user with this email already exists."
            ) from exc

        for topic in topic_list:
            session.add(UserTopic(user_id=user.id, topic=topic))

        session.commit()
        return user.id


def update_user(
    user_id: int,
    language: str | None = None,
    frequency: str | None = None,
    is_active: bool | None = None,
    preferred_time=None,
    preferred_day: str | None = None,
    timezone: str | None = None,
    topics=None,
) -> None:
    """Change only the values that are given (None = keep).

    topics, when given, replaces the whole topic list. Everything is
    validated first and saved in one transaction.
    """
    if frequency is not None and frequency not in {"daily", "weekly"}:
        raise ValueError("Frequency must be daily or weekly.")

    preferred_time, preferred_day, timezone = validate_schedule_values(
        preferred_time, preferred_day, timezone
    )
    topic_list = clean_topics(topics) if topics is not None else None

    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            raise UserNotFound("User not found.")

        if language is not None:
            user.language = language

        if frequency is not None:
            user.frequency = frequency

        if is_active is not None:
            user.is_active = is_active

        if preferred_time is not None:
            if user.preferred_time != preferred_time:
                user.last_run_date = None
            user.preferred_time = preferred_time

        if preferred_day is not None:
            user.preferred_day = preferred_day

        if timezone is not None:
            user.timezone = timezone

        if topic_list is not None:
            current = {
                record.topic: record
                for record in session.scalars(
                    select(UserTopic).where(UserTopic.user_id == user_id)
                ).all()
            }
            wanted = set(topic_list)

            for topic, record in current.items():
                if topic not in wanted:
                    session.delete(record)

            for topic in topic_list:
                if topic not in current:
                    session.add(UserTopic(user_id=user_id, topic=topic))

        session.commit()


def find_user_id_by_email(email: str) -> int | None:
    with SessionLocal() as session:
        return session.scalar(
            select(User.id).where(User.email == email.strip().lower())
        )


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
    preferred_time, preferred_day, timezone = validate_schedule_values(
        preferred_time, preferred_day, timezone
    )

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
