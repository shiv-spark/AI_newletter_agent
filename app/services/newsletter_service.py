import re

from sqlalchemy import select, func

from app.database.db import SessionLocal
from app.database.models import (
    Article,
    NewsletterArticle,
    NewsletterIssue,
    User,
    UserTopic,
)
from app.agents.writing import prepare_newsletter_content
from app.agents.quality_check import validate_newsletter

SPECIAL_CHARACTERS = re.compile(r"([\\.^$|?*+()\[\]{}])")


def build_topic_pattern(topic: str) -> str:
    """Build a regex that matches the topic as a whole word or phrase.

    "AI" matches "New AI model" but not "Spain" or "said".
    """
    topic = " ".join(topic.split())

    if not topic:
        raise ValueError("Topic cannot be empty.")

    # Treat special characters such as + or . as normal text.
    pattern = SPECIAL_CHARACTERS.sub(r"\\\1", topic)
    pattern = pattern.replace(" ", r"\s+")

    # Word boundaries only next to plain English letters or digits,
    # so topics like "C++" or Hindi topics still work.
    if topic[0].isascii() and topic[0].isalnum():
        pattern = r"\m" + pattern

    if topic[-1].isascii() and topic[-1].isalnum():
        pattern = pattern + r"\M"

    return pattern


def generate_newsletter_draft(
    user_id: int,
    max_articles_per_topic: int = 5,
) -> dict:
    """Generate and save a newsletter draft without sending an email."""

    if max_articles_per_topic < 1:
        raise ValueError("max_articles_per_topic must be at least 1.")

    with SessionLocal() as session:
        user = session.get(User, user_id)

        if user is None:
            return {"status": "user_not_found", "user_id": user_id}

        if not user.is_active:
            return {"status": "inactive_user", "user_id": user_id}

        topics = session.scalars(
            select(UserTopic.topic)
            .where(UserTopic.user_id == user_id)
            .order_by(UserTopic.topic)
        ).all()

        if not topics:
            return {"status": "no_topics", "user_id": user_id}

        # Only articles from successfully sent issues count as sent.
        previously_used_article_ids = (
            select(NewsletterArticle.article_id)
            .join(
                NewsletterIssue,
                NewsletterIssue.id == NewsletterArticle.newsletter_issue_id,
            )
            .where(
                NewsletterIssue.user_id == user_id,
                NewsletterIssue.status.in_(["draft", "sent"]),
            )
        )

        article_by_id = {}
        direct_publisher_urls = (
            select(Article.canonical_url)
            .where(
                ~Article.url.ilike("%news.google.com%"),
                Article.canonical_url.is_not(None),
            )
        )

        for topic in topics:
            pattern = build_topic_pattern(topic)

            articles = session.scalars(
                select(Article)
                .where(
                    Article.id.not_in(previously_used_article_ids),
                    (
                        Article.title.regexp_match(pattern, flags="i")
                        | Article.summary.regexp_match(pattern, flags="i")
                    ),
                    ~(
                        Article.url.ilike("%news.google.com%")
                        & Article.canonical_url.in_(direct_publisher_urls)
                    ),
                )
                .order_by(
                    Article.published_at.desc().nullslast(),
                    Article.created_at.desc(),
                )
                .limit(max_articles_per_topic * 3)
            ).all()

            
            candidates = [
                    {
                        "id": article.id,
                        "title": article.title,
                        "url": article.url,
                        "source_name": article.source_name,
                        "published_at": article.published_at,
                        "summary": article.summary or "",
                        "content": article.content or "",
                    }
                    for article in articles
                ]


            prepared = prepare_newsletter_content(
                topic=topic,
                articles=candidates,
                language=user.language,
                max_articles=max_articles_per_topic,
            )

            for item in prepared:
                article_by_id[item["id"]] = item

        if not article_by_id:
            return {
                "status": "no_new_articles",
                "user_id": user_id,
                "topics_checked": topics,
            }

        selected_articles = list(article_by_id.values())

        subject = "Your Personalized News Update"

        sections = []
        for article in selected_articles:
            sections.append(
                f"{article['title']}\n"
                f"Source: {article['source_name']}\n"
                f"{article['ai_summary']}\n"
                f"Read more: {article['url']}"
            )

        body = "\n\n---\n\n".join(sections)
        validation = validate_newsletter(
            subject=subject,
            body=body,
            articles=selected_articles,
        )

        if not validation["passed"]:
            return {
                "status": "quality_check_failed",
                "user_id": user_id,
                "errors": validation["errors"],
                "warnings": validation["warnings"],
            }

        issue = NewsletterIssue(
            user_id=user_id,
            subject=subject,
            body=body,
            status="draft",
        )
        session.add(issue)
        session.flush()

        for article in selected_articles:
            session.add(
                NewsletterArticle(
                    newsletter_issue_id=issue.id,
                    article_id=article["id"],
                )
            )

        session.commit()

        return {
            "status": "draft_created",
            "user_id": user_id,
            "issue_id": issue.id,
            "article_count": len(selected_articles),
            "topics_checked": topics,
        }
