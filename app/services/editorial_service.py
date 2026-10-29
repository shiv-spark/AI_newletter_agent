"""Editorial pipeline: Curator -> Analyst -> Writer -> Editor -> HTML.

generate_editorial_issue() builds one newsletter issue for one user and
saves it with the Editor's verdict as its status:

- approved      the Editor accepted it. Only this status can be emailed.
- needs_review  the Editor could not decide. A person should read it.
- rejected      no acceptable newsletter could be produced.

Nothing is ever sent from here. Sending is a separate step, and
send_newsletter() only sends "approved" issues.
"""
import logging

import requests
from sqlalchemy import select

from app.agents.analyst import analyze_stories
from app.agents.curator import curate_articles
from app.agents.editor import review_and_revise
from app.agents.writer import write_newsletter
from app.config import settings
from app.database.db import SessionLocal
from app.database.models import (
    Article,
    NewsletterArticle,
    NewsletterIssue,
    User,
    UserTopic,
)
from app.services.token_service import generate_user_token
from app.services.html_renderer import build_render_items, render_newsletter
from app.services.topic_matching import build_topic_pattern

logger = logging.getLogger(__name__)

# Articles in issues with these statuses are never offered again.
# Rejected and needs_review issues are not listed: their articles may
# get another chance in a later run.
USED_STATUSES = ["draft", "approved", "sending", "sent", "send_failed"]


def load_candidates(user_id: int) -> dict:
    """Read the user, topics and fresh candidate articles from the database."""
    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            return {"status": "user_not_found", "user_id": user_id}

        if not user.is_active:
            return {"status": "inactive_user", "user_id": user_id}

        topics = list(
            session.scalars(
                select(UserTopic.topic)
                .where(UserTopic.user_id == user_id)
                .order_by(UserTopic.topic)
            ).all()
        )

        if not topics:
            return {"status": "no_topics", "user_id": user_id}

        used_article_ids = (
            select(NewsletterArticle.article_id)
            .join(
                NewsletterIssue,
                NewsletterIssue.id == NewsletterArticle.newsletter_issue_id,
            )
            .where(
                NewsletterIssue.user_id == user_id,
                NewsletterIssue.status.in_(USED_STATUSES),
            )
        )

        google_link = Article.url.ilike("%news.google.com%")
        direct_urls = select(Article.canonical_url).where(
            ~google_link, Article.canonical_url.is_not(None)
        )

        by_id = {}

        for topic in topics:
            pattern = build_topic_pattern(topic)

            articles = session.scalars(
                select(Article)
                .where(
                    Article.id.not_in(used_article_ids),
                    (
                        Article.title.regexp_match(pattern, flags="i")
                        | Article.summary.regexp_match(pattern, flags="i")
                    ),
                    ~(google_link & Article.canonical_url.in_(direct_urls)),
                )
                .order_by(
                    Article.published_at.desc().nullslast(),
                    Article.created_at.desc(),
                )
                .limit(settings.curator_candidate_limit)
            ).all()

            for article in articles:
                by_id.setdefault(
                    article.id,
                    {
                        "id": article.id,
                        "title": article.title,
                        "url": article.url,
                        "source_name": article.source_name,
                        "published_at": article.published_at,
                        "summary": article.summary or "",
                        "content": article.content or "",
                        "_created_at": article.created_at,
                    },
                )

        return {
            "status": "ok",
            "language": user.language,
            "topics": topics,
            "candidates": list(by_id.values()),
        }


def sort_newest_first(candidates: list[dict]) -> list[dict]:
    """Newest first, so the Curator prefers newer stories on equal scores."""
    def key(article):
        published = article.get("published_at")
        created = article["_created_at"]

        return (
            published is not None,
            published or created,
            created,
        )

    return sorted(candidates, key=key, reverse=True)


def save_issue(user_id: int, fields: dict, article_ids: list[int]) -> int:
    with SessionLocal() as session:
        issue = NewsletterIssue(user_id=user_id, **fields)
        session.add(issue)
        session.flush()

        for article_id in article_ids:
            session.add(
                NewsletterArticle(
                    newsletter_issue_id=issue.id,
                    article_id=article_id,
                )
            )

        session.commit()

        return issue.id


def generate_editorial_issue(user_id: int) -> dict:
    """Run the full editorial pipeline for one user and save the issue."""
    loaded = load_candidates(user_id)

    if loaded["status"] != "ok":
        return loaded

    topics = loaded["topics"]
    language = loaded["language"]
    candidates = sort_newest_first(loaded["candidates"])

    if not candidates:
        return {
            "status": "no_new_articles",
            "user_id": user_id,
            "topics_checked": topics,
        }

    # Stage 1: Curator.
    selected = curate_articles(candidates, topics)

    if len(selected) < settings.curator_min_stories:
        return {
            "status": "not_enough_stories",
            "user_id": user_id,
            "found": len(selected),
            "required": settings.curator_min_stories,
        }

    sources = {story["id"]: story for story in selected}

    # Stages 2 to 4: Analyst, Writer, Editor (with corrections).
    # If any AI step fails completely, nothing is saved and nothing is sent.
    try:
        analysis = analyze_stories(selected, topics)
        written = write_newsletter(selected, analysis, topics, language)
        review = review_and_revise(selected, written, language)
    except (ValueError, requests.RequestException) as exc:
        logger.warning("Editorial pipeline failed for user %s: %s", user_id, exc)
        return {
            "status": "editorial_error",
            "user_id": user_id,
            "error": str(exc),
        }

    # The Big Picture was written for the original stories. If stories were
    # dropped it no longer fits, and the Editor does not review it, so it
    # is left out.
    big_picture = None if review.big_picture_stale else analysis.big_picture

    fields = {
        "subject": review.subject,
        "body": review.note or "No stories passed the editorial review.",
        "status": review.status,
        "big_picture": big_picture,
        "editor_feedback": review.feedback_json(),
        "revision_count": review.revision_count,
    }

    # Render whenever there are stories, so a person can read needs_review
    # issues too.
    if review.stories:
        items = build_render_items(review.stories, sources)
        unsub_token = generate_user_token(user_id)
        unsub_url = f"{settings.base_url.rstrip('/')}/unsubscribe?token={unsub_token}"
        html_body, plain_text = render_newsletter(
            review.subject,
            big_picture,
            items,
            language,
            unsubscribe_url=unsub_url,
        )
        fields["html_body"] = html_body
        fields["body"] = plain_text

    issue_id = save_issue(
        user_id, fields, [story.article_id for story in review.stories]
    )

    return {
        "status": review.status,
        "user_id": user_id,
        "issue_id": issue_id,
        "article_count": len(review.stories),
        "revision_count": review.revision_count,
        "dropped_article_ids": review.dropped_article_ids,
        "note": review.note,
    }
