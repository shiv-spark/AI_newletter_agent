from datetime import datetime, timezone

from sqlalchemy import select, update

from app.database.db import SessionLocal
from app.database.models import (
    Article,
    NewsletterArticle,
    NewsletterIssue,
    User,
)
from app.services.email_service import send_email


def send_newsletter(issue_id: int) -> dict:
    """Send a saved draft and update its delivery status."""

    # Step 1: Validate and claim the draft atomically.
    with SessionLocal() as session:
        issue = session.get(NewsletterIssue, issue_id)

        if issue is None:
            return {
                "status": "issue_not_found",
                "issue_id": issue_id,
            }

        if issue.status != "draft":
            return {
                "status": "not_sendable",
                "issue_id": issue_id,
                "current_status": issue.status,
            }

        user = session.get(User, issue.user_id)

        if user is None:
            return {
                "status": "user_not_found",
                "issue_id": issue_id,
            }

        if not user.is_active:
            return {
                "status": "inactive_user",
                "issue_id": issue_id,
            }

        article_ids = session.scalars(
            select(NewsletterArticle.article_id).where(
                NewsletterArticle.newsletter_issue_id == issue_id
            )
        ).all()

        if not article_ids:
            return {
                "status": "no_articles",
                "issue_id": issue_id,
            }

        # Prevent articles already sent to this user from being resent
        # through a different newsletter issue.
        already_sent_ids = set(
            session.scalars(
                select(NewsletterArticle.article_id)
                .join(
                    NewsletterIssue,
                    NewsletterIssue.id
                    == NewsletterArticle.newsletter_issue_id,
                )
                .where(
                    NewsletterIssue.user_id == user.id,
                    NewsletterIssue.status == "sent",
                    NewsletterArticle.article_id.in_(article_ids),
                )
            ).all()
        )

        if already_sent_ids:
            return {
                "status": "duplicate_articles_already_sent",
                "issue_id": issue_id,
                "article_ids": sorted(already_sent_ids),
            }

        # Only one concurrent caller can claim this draft.
        claim = session.execute(
            update(NewsletterIssue)
            .where(
                NewsletterIssue.id == issue_id,
                NewsletterIssue.status == "draft",
            )
            .values(status="sending")
        )

        if claim.rowcount != 1:
            session.rollback()
            return {
                "status": "not_sendable",
                "issue_id": issue_id,
                "message": "Another process has already claimed this issue.",
            }

        # Copy values before closing the database session.
        recipient = user.email
        subject = issue.subject
        body = issue.body

        session.commit()

    # Step 2: Send the email outside the database transaction.
    try:
        result = send_email(
            to_email=recipient,
            subject=subject,
            body=body,
        )
    except Exception:
        result = {
            "success": False,
            "error": "Unexpected email-service error; delivery may be uncertain.",
        }

    # Step 3: Record the outcome.
    with SessionLocal() as session:
        issue = session.get(NewsletterIssue, issue_id)

        if issue is None:
            return {
                "status": "delivery_recording_error",
                "issue_id": issue_id,
            }

        if result.get("success"):
            issue.status = "sent"
            issue.sent_at = datetime.now(timezone.utc)
            session.commit()

            return {
                "status": "sent",
                "issue_id": issue_id,
                "recipient": recipient,
                "message_id": result.get("message_id"),
            }

        # Do not automatically retry an uncertain delivery.
        issue.status = "send_failed"
        session.commit()

        return {
            "status": "send_failed",
            "issue_id": issue_id,
            "error": result.get("error", "Unknown email-service error."),
            "manual_review_required": True,
        }
