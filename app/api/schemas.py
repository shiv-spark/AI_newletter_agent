"""Request and response shapes of the web API."""
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    topics: list[str] = Field(default_factory=list)
    frequency: Literal["daily", "weekly"] = "daily"
    language: str = Field(default="en", min_length=2, max_length=20)
    preferred_time: str = "08:00"          # HH:MM, in the user's timezone
    preferred_day: str | None = None       # weekly users, for example "monday"
    timezone: str = "Asia/Kolkata"         # IANA name

    @field_validator("email")
    @classmethod
    def _email_looks_valid(cls, value: str) -> str:
        value = value.strip().lower()

        if not EMAIL_PATTERN.match(value):
            raise ValueError("Enter a valid email address.")

        return value


class PreferencesUpdate(BaseModel):
    """Only the fields that are sent are changed."""

    topics: list[str] | None = None        # replaces the whole topic list
    frequency: Literal["daily", "weekly"] | None = None
    language: str | None = Field(default=None, min_length=2, max_length=20)
    is_active: bool | None = None
    preferred_time: str | None = None
    preferred_day: str | None = None
    timezone: str | None = None


class PreferencesOut(BaseModel):
    id: int
    email: str
    language: str
    frequency: str
    is_active: bool
    preferred_time: str
    preferred_day: str | None
    timezone: str
    topics: list[str]


class GenerateNow(BaseModel):
    user_id: int
    research: bool = True   # collect fresh articles first


class RunState(BaseModel):
    state: Literal["idle", "running", "finished", "failed"]
    status: str | None = None       # editorial result, e.g. "approved"
    issue_id: int | None = None
    error: str | None = None
    task_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IssueSummary(BaseModel):
    id: int
    user_id: int
    subject: str
    status: str
    created_at: datetime
    sent_at: datetime | None = None


class IssueDetail(IssueSummary):
    article_count: int
    revision_count: int
    big_picture: str | None = None
    editor_feedback: dict | None = None
    has_html: bool
    preview_url: str
