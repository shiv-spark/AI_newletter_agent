
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False
    )
    language: Mapped[str] = mapped_column(
        String(20), default="en", nullable=False
    )
    frequency: Mapped[str] = mapped_column(
        String(20), default="daily", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    preferred_time: Mapped[time] = mapped_column(
        Time,
        default=time(8, 0),
        server_default="08:00:00",
        nullable=False,
    )
    preferred_day: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    timezone: Mapped[str] = mapped_column(
        String(50),
        default="Asia/Kolkata",
        server_default="Asia/Kolkata",
        nullable=False,
    )
    last_run_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UserTopic(Base):
    __tablename__ = "user_topics"
    __table_args__ = (
        UniqueConstraint("user_id", "topic", name="uq_user_topic"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(100), nullable=False)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(
        String(2048), unique=True, nullable=False
    )
    canonical_url: Mapped[str] = mapped_column(
        String(2048), unique=True, nullable=False
    )
    source_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    summary: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class NewsletterIssue(Base):
    __tablename__ = "newsletter_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    subject: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="draft", nullable=False
    )
    # Rendered responsive HTML email. The plain-text version stays in `body`.
    html_body: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # Analyst Agent's cross-story summary ("The Big Picture").
    big_picture: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # Last Editor verdict stored as a JSON string (audit trail).
    editor_feedback: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # Number of Writer revisions that were needed for this issue.
    revision_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class NewsletterArticle(Base):
    __tablename__ = "newsletter_articles"
    __table_args__ = (
        UniqueConstraint(
            "newsletter_issue_id",
            "article_id",
            name="uq_newsletter_article",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    newsletter_issue_id: Mapped[int] = mapped_column(
        ForeignKey("newsletter_issues.id", ondelete="CASCADE"),
        nullable=False,
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False
    )
