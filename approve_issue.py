"""Manually approve a newsletter the Editor could not judge.

Use this for an issue whose status is 'needs_review'. The Editor model
failed to give a usable verdict, so a person must read the newsletter.

    python approve_issue.py you@example.com

It shows the newest issue and asks for YES. If you confirm, the issue
becomes 'approved' (the decision is recorded in editor_feedback). Then send
it with:   python send_draft.py you@example.com

Issues the Editor REJECTED (it found real problems) cannot be approved here.
Create a new one instead: python run_now.py you@example.com
"""
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.database.db import SessionLocal
from app.database.models import NewsletterIssue, User


def approve_needs_review_issue(issue: NewsletterIssue) -> None:
    """Mark a needs_review issue as approved by a person."""
    if issue.status != "needs_review":
        raise ValueError(
            f"Only 'needs_review' issues can be approved by hand; "
            f"this one is '{issue.status}'."
        )

    try:
        feedback = json.loads(issue.editor_feedback or "{}")
    except ValueError:
        feedback = {}

    feedback["manually_approved_at"] = datetime.now(timezone.utc).isoformat()
    feedback["previous_status"] = issue.status

    issue.editor_feedback = json.dumps(feedback, ensure_ascii=False)
    issue.status = "approved"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python approve_issue.py you@example.com")
        return

    email = sys.argv[1].strip().lower()

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
            print("No newsletter yet.")
            return

        if issue.status != "needs_review":
            print(f"The newest issue ({issue.id}) is '{issue.status}'.")
            print("Only 'needs_review' issues can be approved by hand.")
            return

        print(f"Issue {issue.id} | Subject: {issue.subject}")
        print("-" * 60)
        print(issue.body)
        print("-" * 60)
        print("Read it carefully: check names, numbers and dates against the sources.")

        if input("Type YES to approve this issue: ").strip() != "YES":
            print("Cancelled. Nothing changed.")
            return

        approve_needs_review_issue(issue)
        session.commit()

    print(f"Approved. Now send it: python send_draft.py {email}")


if __name__ == "__main__":
    main()
