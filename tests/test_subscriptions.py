"""Tests for user unsubscribe and subscribe functionality."""
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete

from app.database.db import SessionLocal
from app.database.models import User
from app.main import app
from app.services.token_service import generate_user_token, verify_user_token


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_user():
    email = f"sub-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as session:
        user = User(email=email, is_active=True)
        session.add(user)
        session.commit()
        user_id = user.id

    yield {"id": user_id, "email": email}

    with SessionLocal() as session:
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_token_service_generate_and_verify():
    token = generate_user_token(42)
    assert verify_user_token(token) == 42

    # Tampered token fails
    assert verify_user_token(token + "tamper") is None
    assert verify_user_token("invalid_format") is None
    assert verify_user_token("abc.invalid") is None
    assert verify_user_token("") is None


def test_unsubscribe_endpoint_sets_is_active_false(client, test_user):
    token = generate_user_token(test_user["id"])
    response = client.get(f"/unsubscribe?token={token}")

    assert response.status_code == 200
    assert "You have unsubscribed" in response.text
    assert "Resubscribe" in response.text
    assert test_user["email"] in response.text

    # Verify database column is updated to False
    with SessionLocal() as session:
        u = session.get(User, test_user["id"])
        assert u.is_active is False


def test_subscribe_endpoint_sets_is_active_true(client, test_user):
    # First deactivate
    with SessionLocal() as session:
        u = session.get(User, test_user["id"])
        u.is_active = False
        session.commit()

    token = generate_user_token(test_user["id"])
    response = client.get(f"/subscribe?token={token}")

    assert response.status_code == 200
    assert "Welcome back" in response.text
    assert test_user["email"] in response.text

    # Verify database column is updated to True
    with SessionLocal() as session:
        u = session.get(User, test_user["id"])
        assert u.is_active is True


def test_invalid_token_returns_400(client):
    response = client.get("/unsubscribe?token=fake.token123")
    assert response.status_code == 400


def test_unknown_user_returns_404(client):
    token = generate_user_token(99999999)
    response = client.get(f"/unsubscribe?token={token}")
    assert response.status_code == 404
