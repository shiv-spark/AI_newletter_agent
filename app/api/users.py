"""User registration and preferences."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import (
    GenerateNow,
    IssueSummary,
    PreferencesOut,
    PreferencesUpdate,
    RunState,
    UserCreate,
)
from app.api.security import require_api_key
from app.database.db import SessionLocal
from app.database.models import NewsletterIssue
from app.services import user_preferences as prefs
from sqlalchemy import select

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_api_key)],
)


def _load(user_id: int) -> dict:
    data = prefs.get_user_preferences(user_id)

    if data is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return data


@router.post("", response_model=PreferencesOut, status_code=201)
def register_user(body: UserCreate):
    """Register a user with topics, frequency, time and timezone."""
    try:
        user_id = prefs.register_user(
            email=body.email,
            topics=body.topics,
            language=body.language,
            frequency=body.frequency,
            preferred_time=body.preferred_time,
            preferred_day=body.preferred_day,
            timezone=body.timezone,
        )
    except prefs.UserAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _load(user_id)


@router.get("", response_model=PreferencesOut)
def find_user(email: str = Query(min_length=3)):
    """Look a user up by email address."""
    user_id = prefs.find_user_id_by_email(email)

    if user_id is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return _load(user_id)


@router.get("/{user_id}/preferences", response_model=PreferencesOut)
def get_preferences(user_id: int):
    return _load(user_id)


@router.patch("/{user_id}/preferences", response_model=PreferencesOut)
def update_preferences(user_id: int, body: PreferencesUpdate):
    """Change topics, schedule or language. Only sent fields change."""
    try:
        prefs.update_user(user_id, **body.model_dump(exclude_unset=True))
    except prefs.UserNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _load(user_id)


@router.get("/{user_id}/issues", response_model=list[IssueSummary])
def list_issues(user_id: int, limit: int = Query(default=20, ge=1, le=100)):
    """Past issues of a user, newest first."""
    _load(user_id)

    with SessionLocal() as session:
        issues = session.scalars(
            select(NewsletterIssue)
            .where(NewsletterIssue.user_id == user_id)
            .order_by(NewsletterIssue.id.desc())
            .limit(limit)
        ).all()

        return [
            IssueSummary(
                id=i.id, user_id=i.user_id, subject=i.subject,
                status=i.status, created_at=i.created_at, sent_at=i.sent_at,
            )
            for i in issues
        ]


@router.get("/{user_id}/run-status", response_model=RunState)
def run_status(user_id: int):
    """State of the latest on-demand run for this user."""
    from app.api.issues import get_run_state

    _load(user_id)
    return get_run_state(user_id)
