"""Send the newest APPROVED newsletter of a user by email.

Run from the project folder:
    python send_draft.py you@example.com          (asks before sending)
    python send_draft.py you@example.com --yes    (sends without asking)

The email goes to the user's own email address.
"""
import sys

from sqlalchemy import func, select

from app.config import settings
from app.database.db import SessionLocal
from app.database.models import NewsletterArticle, NewsletterIssue, User
from app.services.delivery_service import send_newsletter


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python send_draft.py you@example.com")
        return

    email = sys.argv[1].strip().lower()
    skip_question = "--yes" in sys.argv

    if not settings.resend_api_key or not settings.resend_from_email:
        print("Email is not set up. Add these two lines to your .env file:")
        print("  RESEND_API_KEY=re_xxxxxxxx")
        print("  RESEND_FROM_EMAIL=onboarding@resend.dev")
        return

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))

        if user is None:
            print("No user with this email.")
            return

        issue = session.scalar(
            select(NewsletterIssue)
            .where(NewsletterIssue.user_id == user.id)
            .order_by(NewsletterIssue.id.desc())
            .limit(1)
        )

        if issue is None:
            print(f"No newsletter yet. Create one: python run_now.py {email}")
            return

        if issue.status != "approved":
            print(f"The newest issue ({issue.id}) is '{issue.status}', not 'approved'.")
            print("Only issues approved by the Editor can be sent.")
            print(f"Create a new issue: python run_now.py {email}")
            return

        article_count = session.scalar(
            select(func.count(NewsletterArticle.id)).where(
                NewsletterArticle.newsletter_issue_id == issue.id
            )
        )
        issue_id = issue.id
        subject = issue.subject

    print(f"To:       {email}")
    print(f"From:     {settings.resend_from_email}")
    print(f"Subject:  {subject}")
    print(f"Articles: {article_count}")

    if not skip_question:
        answer = input("Type YES to send this email now: ")

        if answer.strip() != "YES":
            print("Cancelled. Nothing was sent.")
            return

    result = send_newsletter(issue_id)
    print(f"Result: {result}")

    if result["status"] == "sent":
        print("Sent. Check your inbox, and also the spam folder.")
    else:
        print("Not sent. Read the Result line above for the reason.")


if __name__ == "__main__":
    main()