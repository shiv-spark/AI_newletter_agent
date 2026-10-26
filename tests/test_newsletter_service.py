import uuid
from unittest.mock import patch

from sqlalchemy import delete

from app.database.db import SessionLocal
from app.database.models import (
    Article,
    NewsletterArticle,
    NewsletterIssue,
    User,
    UserTopic,
)
from app.services.newsletter_service import generate_newsletter_draft


def test_unknown_user_does_not_create_draft():
    result = generate_newsletter_draft(user_id=-999999)

    assert result["status"] == "user_not_found"


def test_user_without_topics_does_not_create_draft():
    email = f"newsletter-test-{uuid.uuid4().hex}@example.com"
    user_id = None

    try:
        with SessionLocal() as session:
            user = User(email=email)
            session.add(user)
            session.commit()
            user_id = user.id

        result = generate_newsletter_draft(user_id)

        assert result["status"] == "no_topics"

    finally:
        if user_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(NewsletterArticle).where(
                        NewsletterArticle.newsletter_issue_id.in_(
                            select_issue_ids(user_id)
                        )
                    )
                )
                session.execute(
                    delete(NewsletterIssue).where(
                        NewsletterIssue.user_id == user_id
                    )
                )
                session.execute(
                    delete(UserTopic).where(UserTopic.user_id == user_id)
                )
                session.execute(delete(User).where(User.id == user_id))
                session.commit()


def select_issue_ids(user_id):
    from sqlalchemy import select

    return select(NewsletterIssue.id).where(
        NewsletterIssue.user_id == user_id
    )


def test_draft_excludes_articles_already_sent_to_user():
    email = f"newsletter-test-{uuid.uuid4().hex}@example.com"
    unique_id = uuid.uuid4().hex
    # A unique made-up topic, so real articles in the database cannot match.
    topic = f"zq{unique_id[:8]}"
    user_id = None
    article_ids = []

    try:
        with SessionLocal() as session:
            user = User(email=email)
            session.add(user)
            session.flush()
            user_id = user.id

            session.add(UserTopic(user_id=user_id, topic=topic))

            sent_article = Article(
                title=f"Story already sent {topic}",
                url=f"https://example.com/sent-{unique_id}",
                canonical_url=f"https://example.com/sent-{unique_id}",
                source_name="Example News",
                content_hash=f"sent-{unique_id}",
                summary=f"An already sent story about {topic}.",
            )

            new_article = Article(
                title=f"Story not sent {topic}",
                url=f"https://example.com/new-{unique_id}",
                canonical_url=f"https://example.com/new-{unique_id}",
                source_name="Example News",
                content_hash=f"new-{unique_id}",
                summary=f"A new story about {topic} for the newsletter.",
            )

            session.add_all([sent_article, new_article])
            session.flush()

            article_ids = [sent_article.id, new_article.id]

            sent_issue = NewsletterIssue(
                user_id=user_id,
                subject="Previous newsletter",
                body="Previously sent content",
                status="sent",
            )
            session.add(sent_issue)
            session.flush()

            session.add(
                NewsletterArticle(
                    newsletter_issue_id=sent_issue.id,
                    article_id=sent_article.id,
                )
            )
            session.commit()

        def fake_prepare_newsletter_content(
            topic, articles, language="en", max_articles=5
        ):
            sent_url = f"https://example.com/sent-{unique_id}"
            new_url = f"https://example.com/new-{unique_id}"

            candidate_urls = {article["url"] for article in articles}

            # The previously sent article must not be eligible.
            assert sent_url not in candidate_urls

            # The new article must be eligible.
            assert new_url in candidate_urls

            # Keep this test isolated from unrelated articles in PostgreSQL.
            return [
                {
                    **article,
                    "ai_summary": "A concise AI news summary.",
                }
                for article in articles
                if article["url"] == new_url
            ]
     

        with patch(
            "app.services.newsletter_service.prepare_newsletter_content",
            side_effect=fake_prepare_newsletter_content,
        ):
            result = generate_newsletter_draft(user_id)

        assert result["status"] == "draft_created"
        assert result["article_count"] == 1

        with SessionLocal() as session:
            draft = session.get(NewsletterIssue, result["issue_id"])
            assert draft is not None
            assert draft.status == "draft"

            linked_ids = session.scalars(
                select_article_ids(result["issue_id"])
            ).all()

            assert linked_ids == [article_ids[1]]
            assert article_ids[0] not in linked_ids

    finally:
        if user_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(NewsletterArticle).where(
                        NewsletterArticle.newsletter_issue_id.in_(
                            select_issue_ids(user_id)
                        )
                    )
                )
                session.execute(
                    delete(NewsletterIssue).where(
                        NewsletterIssue.user_id == user_id
                    )
                )
                session.execute(
                    delete(UserTopic).where(UserTopic.user_id == user_id)
                )

                if article_ids:
                    session.execute(
                        delete(Article).where(Article.id.in_(article_ids))
                    )

                session.execute(delete(User).where(User.id == user_id))
                session.commit()


def select_article_ids(issue_id):
    from sqlalchemy import select

    return select(NewsletterArticle.article_id).where(
        NewsletterArticle.newsletter_issue_id == issue_id
    )