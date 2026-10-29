"""Show the newest newsletter issue of a user.

Run from the project folder:
    python check_test_user.py you@example.com
"""
import json
import sys

from sqlalchemy import select

from app.database.db import SessionLocal
from app.database.models import NewsletterIssue, User


def print_editor_feedback(raw: str | None) -> None:
    """Show why the Editor rejected or corrected the newsletter."""
    if not raw:
        return

    try:
        feedback = json.loads(raw)
    except ValueError:
        print("Editor feedback (unreadable):", raw)
        return

    print("-" * 60)
    print(f"Editor note: {feedback.get('note') or '-'}")

    for number, verdict in enumerate(feedback.get("history", []), start=1):
        print(f"Editor round {number}: {verdict.get('status')}")

        for item in verdict.get("issues", []):
            target = (
                "SUBJECT/GENERAL"
                if item.get("article_id") is None
                else f"story {item['article_id']}"
            )
            print(f"   - [{target}] {item.get('problem')}")
            print(f"       fix: {item.get('correction')}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python check_test_user.py you@example.com")
        return

    email = sys.argv[1].strip().lower()

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))

        if user is None:
            print("No user with this email.")
            return

        print(f"last_run_date: {user.last_run_date}")

        issue = session.scalar(
            select(NewsletterIssue)
            .where(NewsletterIssue.user_id == user.id)
            .order_by(NewsletterIssue.id.desc())
            .limit(1)
        )

        if issue is None:
            print("No newsletter yet. Wait a little, or check the app log.")
            return

        print(f"Issue {issue.id}, status: {issue.status}")
        print(f"Subject: {issue.subject}")
        print(f"HTML version: {'yes' if issue.html_body else 'no'}")
        print(f"Corrections by the writer: {issue.revision_count}")
        print_editor_feedback(issue.editor_feedback)
        print("-" * 60)
        print(issue.body)


if __name__ == "__main__":
    main()