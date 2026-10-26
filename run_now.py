"""Run research + the editorial pipeline for one user (no email is sent).

Run from the project folder:
    python run_now.py you@example.com
"""
import sys

from sqlalchemy import select

from app.database.db import SessionLocal
from app.database.models import User
from app.services.scheduler_service import run_newsletter_for_user


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_now.py you@example.com")
        return

    email = sys.argv[1].strip().lower()

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))

    if user is None:
        print("No user with this email.")
        print(f"Create one first: python create_test_user.py {email}")
        return

    if not user.is_active:
        print("This user is inactive. Turn the user on first.")
        return

    print("Running research and the editorial pipeline. No email is sent.")
    print("This can take a few minutes...")

    status = run_newsletter_for_user(user.id, send_emails=False)

    print(f"Result: {status}")
    print(f"Read the issue with: python check_test_user.py {email}")


if __name__ == "__main__":
    main()
