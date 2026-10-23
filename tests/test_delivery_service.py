import uuid
from unittest.mock import patch

from sqlalchemy import delete, select

from app.database.db import SessionLocal
from app.database.models import (
    Article,
    NewsletterArticle,
    NewsletterIssue,
    User,
)
from app.services.delivery_service import send_newsletter


def create_test_draft():
    """Create a unique user, article, and newsletter draft in PostgreSQL."""
    unique_id = uuid.uuid4().hex

    with SessionLocal() as session:
        user = User(email=f"delivery-test-{unique_id}@example.com")
        session.add(user)
        session.flush()

        article = Article(
            title=f"Delivery test article {unique_id}",
            url=f"https://example.com/delivery/{unique_id}",
            canonical_url=f"https://example.com/delivery/{unique_id}",
            source_name="Example News",
            content_hash=unique_id,
            summary="Test article summary.",
        )
        session.add(article)
        session.flush()

        issue = NewsletterIssue(
            user_id=user.id,
            subject="Delivery test newsletter",
            body="This is a test newsletter.",
            status="draft",
        )
        session.add(issue)
        session.flush()

        session.add(
            NewsletterArticle(
                newsletter_issue_id=issue.id,
                article_id=article.id,
            )
        )

        result = {
            "user_id": user.id,
            "article_id": article.id,
            "issue_id": issue.id,
        }
        session.commit()

        return result


def cleanup_test_data(test_data):
    """Delete only the records created by this test."""
    with SessionLocal() as session:
        issue_ids = select(NewsletterIssue.id).where(
            NewsletterIssue.user_id == test_data["user_id"]
        )

        session.execute(
            delete(NewsletterArticle).where(
                NewsletterArticle.newsletter_issue_id.in_(issue_ids)
            )
        )
        session.execute(
            delete(NewsletterIssue).where(
                NewsletterIssue.user_id == test_data["user_id"]
            )
        )
        session.execute(
            delete(Article).where(
                Article.id == test_data["article_id"]
            )
        )
        session.execute(
            delete(User).where(User.id == test_data["user_id"])
        )
        session.commit()


def test_successful_delivery_marks_issue_sent():
    test_data = create_test_draft()

    try:
        with patch(
            "app.services.delivery_service.send_email",
            return_value={
                "success": True,
                "message_id": "mock-message-123",
            },
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "sent"
        assert result["message_id"] == "mock-message-123"
        mock_send.assert_called_once()

        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            assert issue.status == "sent"
            assert issue.sent_at is not None

    finally:
        cleanup_test_data(test_data)


def test_failed_delivery_does_not_mark_issue_sent():
    test_data = create_test_draft()

    try:
        with patch(
            "app.services.delivery_service.send_email",
            return_value={
                "success": False,
                "error": "Mock email failure",
            },
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "send_failed"
        assert result["manual_review_required"] is True
        mock_send.assert_called_once()

        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            assert issue.status == "send_failed"
            assert issue.sent_at is None

    finally:
        cleanup_test_data(test_data)


def test_already_sent_issue_is_not_sent_again():
    test_data = create_test_draft()

    try:
        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            issue.status = "sent"
            session.commit()

        with patch(
            "app.services.delivery_service.send_email"
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "not_sendable"
        assert result["current_status"] == "sent"
        mock_send.assert_not_called()

    finally:
        cleanup_test_data(test_data)


def test_unknown_issue_is_not_sent():
    with patch(
        "app.services.delivery_service.send_email"
    ) as mock_send:
        result = send_newsletter(-999999)

    assert result["status"] == "issue_not_found"
    mock_send.assert_not_called()


def test_article_already_sent_in_another_issue_is_rejected():
    test_data = create_test_draft()
    duplicate_issue_id = None

    try:
        with SessionLocal() as session:
            original_issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            original_issue.status = "sent"

            duplicate_issue = NewsletterIssue(
                user_id=test_data["user_id"],
                subject="Duplicate newsletter",
                body="This contains an already-sent article.",
                status="draft",
            )
            session.add(duplicate_issue)
            session.flush()
            duplicate_issue_id = duplicate_issue.id

            session.add(
                NewsletterArticle(
                    newsletter_issue_id=duplicate_issue.id,
                    article_id=test_data["article_id"],
                )
            )
            session.commit()

        with patch(
            "app.services.delivery_service.send_email"
        ) as mock_send:
            result = send_newsletter(duplicate_issue_id)

        assert result["status"] == "duplicate_articles_already_sent"
        assert test_data["article_id"] in result["article_ids"]
        mock_send.assert_not_called()

    finally:
        if duplicate_issue_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(NewsletterArticle).where(
                        NewsletterArticle.newsletter_issue_id
                        == duplicate_issue_id
                    )
                )
                session.execute(
                    delete(NewsletterIssue).where(
                        NewsletterIssue.id == duplicate_issue_id
                    )
                )
                session.commit()

        cleanup_test_data(test_data)


def test_inactive_user_is_not_sent_newsletter():
    test_data = create_test_draft()

    try:
        with SessionLocal() as session:
            user = session.get(User, test_data["user_id"])
            user.is_active = False
            session.commit()

        with patch(
            "app.services.delivery_service.send_email"
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "inactive_user"
        mock_send.assert_not_called()

        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            assert issue.status == "draft"

    finally:
        cleanup_test_data(test_data)

def test_newsletter_without_articles_is_not_sent():
    test_data = create_test_draft()

    try:
        with SessionLocal() as session:
            session.execute(
                delete(NewsletterArticle).where(
                    NewsletterArticle.newsletter_issue_id
                    == test_data["issue_id"]
                )
            )
            session.commit()

        with patch(
            "app.services.delivery_service.send_email"
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "no_articles"
        mock_send.assert_not_called()

        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            assert issue.status == "draft"

    finally:
        cleanup_test_data(test_data)


def test_unexpected_email_exception_requires_manual_review():
    test_data = create_test_draft()

    try:
        with patch(
            "app.services.delivery_service.send_email",
            side_effect=RuntimeError("Mock unexpected email error"),
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "send_failed"
        assert result["manual_review_required"] is True
        mock_send.assert_called_once()

        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            assert issue.status == "send_failed"
            assert issue.sent_at is None

    finally:
        cleanup_test_data(test_data)


def test_issue_already_being_sent_is_not_sent_again():
    test_data = create_test_draft()

    try:
        with SessionLocal() as session:
            issue = session.get(
                NewsletterIssue, test_data["issue_id"]
            )
            issue.status = "sending"
            session.commit()

        with patch(
            "app.services.delivery_service.send_email"
        ) as mock_send:
            result = send_newsletter(test_data["issue_id"])

        assert result["status"] == "not_sendable"
        assert result["current_status"] == "sending"
        mock_send.assert_not_called()

    finally:
        cleanup_test_data(test_data)
