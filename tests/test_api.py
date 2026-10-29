import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api import issues as issues_api
from app.config import settings
from app.database.db import SessionLocal
from app.database.models import NewsletterIssue, User
from app.main import app


@pytest.fixture
def client():
    # No "with": the scheduler in the app lifespan must not start in tests.
    return TestClient(app)


@pytest.fixture
def emails():
    """Collects the emails a test creates and deletes those users afterwards."""
    created = []
    yield created

    with SessionLocal() as session:
        ids = session.scalars(select(User.id).where(User.email.in_(created))).all()
        session.execute(
            delete(NewsletterIssue).where(NewsletterIssue.user_id.in_(ids))
        )
        session.execute(delete(User).where(User.id.in_(ids)))
        session.commit()


@pytest.fixture(autouse=True)
def clean_run_state():
    issues_api._runs.clear()
    yield
    issues_api._runs.clear()


def register(client, emails, **overrides):
    email = f"api-{uuid.uuid4().hex[:10]}@example.com"
    emails.append(email)
    body = {"email": email, "topics": ["AI", "Climate"], **overrides}
    return client.post("/api/users", json=body)


def make_issue(user_id, html_body="<html><body>Hello</body></html>", status="approved"):
    with SessionLocal() as session:
        issue = NewsletterIssue(
            user_id=user_id,
            subject="Test subject",
            body="Plain text body",
            status=status,
            html_body=html_body,
            big_picture="Big picture.",
            editor_feedback=json.dumps({"status": "approved", "issues": []}),
        )
        session.add(issue)
        session.commit()
        return issue.id


# ---------------------------------------------------------------- register

def test_register_user_with_topics_and_schedule(client, emails):
    response = register(
        client, emails,
        frequency="weekly", preferred_day="Friday",
        preferred_time="07:30", timezone="Europe/London", language="hi",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["topics"] == ["AI", "Climate"]
    assert data["frequency"] == "weekly"
    assert data["preferred_day"] == "friday"
    assert data["preferred_time"] == "07:30"
    assert data["timezone"] == "Europe/London"
    assert data["language"] == "hi"
    assert data["is_active"] is True


def test_register_uses_defaults(client, emails):
    data = register(client, emails).json()

    assert data["frequency"] == "daily"
    assert data["preferred_time"] == "08:00"
    assert data["timezone"] == "Asia/Kolkata"
    assert data["language"] == "en"


def test_topics_are_cleaned_and_deduplicated(client, emails):
    data = register(
        client, emails, topics=["  AI ", "ai", "", "Machine   Learning"]
    ).json()

    assert data["topics"] == ["AI", "Machine Learning"]


def test_duplicate_email_is_rejected(client, emails):
    first = register(client, emails)
    second = client.post(
        "/api/users", json={"email": first.json()["email"].upper()}
    )

    assert second.status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"timezone": "Mars/Base"},
        {"preferred_time": "25:99"},
        {"preferred_time": "8am"},
        {"preferred_day": "someday"},
        {"frequency": "hourly"},
        {"topics": ["x" * 101]},
        {"topics": [f"topic {n}" for n in range(21)]},
    ],
)
def test_invalid_values_are_rejected_and_nothing_is_saved(client, emails, overrides):
    response = register(client, emails, **overrides)

    assert response.status_code == 422
    email = emails[-1]

    with SessionLocal() as session:
        assert session.scalar(select(User).where(User.email == email)) is None


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "a b@c.com"])
def test_invalid_email_is_rejected(client, email):
    assert client.post("/api/users", json={"email": email}).status_code == 422


# ------------------------------------------------------------- preferences

def test_get_preferences_and_lookup_by_email(client, emails):
    created = register(client, emails).json()

    by_id = client.get(f"/api/users/{created['id']}/preferences")
    by_email = client.get("/api/users", params={"email": created["email"]})

    assert by_id.status_code == 200 and by_id.json() == created
    assert by_email.status_code == 200 and by_email.json() == created


def test_unknown_user_is_404(client):
    assert client.get("/api/users/99999999/preferences").status_code == 404
    assert client.get("/api/users", params={"email": "nobody@nowhere.com"}).status_code == 404
    assert client.patch("/api/users/99999999/preferences", json={}).status_code == 404
    assert client.get("/api/users/99999999/issues").status_code == 404


def test_patch_changes_only_the_given_fields(client, emails):
    created = register(client, emails, preferred_time="06:00").json()

    response = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"preferred_time": "21:15"},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["preferred_time"] == "21:15"
    assert data["topics"] == ["AI", "Climate"]
    assert data["timezone"] == created["timezone"]


def test_patch_replaces_the_topic_list(client, emails):
    created = register(client, emails, topics=["AI", "Climate"]).json()

    data = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"topics": ["Climate", "Space"]},
    ).json()

    assert data["topics"] == ["Climate", "Space"]


def test_patch_can_deactivate_and_empty_the_topics(client, emails):
    created = register(client, emails).json()

    data = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"is_active": False, "topics": []},
    ).json()

    assert data["is_active"] is False
    assert data["topics"] == []


def test_invalid_patch_changes_nothing(client, emails):
    created = register(client, emails).json()

    response = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"preferred_time": "07:00", "timezone": "Mars/Base"},
    )

    assert response.status_code == 422
    after = client.get(f"/api/users/{created['id']}/preferences").json()
    assert after["preferred_time"] == "08:00"


# ------------------------------------------------------------ generate-now

def fake_pipeline(monkeypatch, status="approved", issue_id=123, fail=False):
    calls = {"research": 0, "editorial": 0}

    def research(user_id):
        calls["research"] += 1

    def editorial(user_id):
        calls["editorial"] += 1
        if fail:
            raise RuntimeError("secret internal detail")
        return {"status": status, "user_id": user_id, "issue_id": issue_id}

    monkeypatch.setattr(issues_api, "run_user_research", research)
    monkeypatch.setattr(issues_api, "generate_editorial_issue", editorial)
    return calls


def test_generate_now_runs_the_pipeline_and_reports_the_result(client, emails, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    user = register(client, emails).json()

    response = client.post("/api/issues/generate-now", json={"user_id": user["id"]})

    assert response.status_code == 202
    assert response.json()["state"] == "running"
    assert calls == {"research": 1, "editorial": 1}

    state = client.get(f"/api/users/{user['id']}/run-status").json()
    assert state["state"] == "finished"
    assert state["status"] == "approved"
    assert state["issue_id"] == 123
    assert state["finished_at"] is not None


def test_generate_now_can_skip_research(client, emails, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    user = register(client, emails).json()

    client.post(
        "/api/issues/generate-now", json={"user_id": user["id"], "research": False}
    )

    assert calls == {"research": 0, "editorial": 1}


def test_failed_run_is_reported_without_internal_details(client, emails, monkeypatch):
    fake_pipeline(monkeypatch, fail=True)
    user = register(client, emails).json()

    client.post("/api/issues/generate-now", json={"user_id": user["id"]})
    state = client.get(f"/api/users/{user['id']}/run-status").json()

    assert state["state"] == "failed"
    assert "secret internal detail" not in json.dumps(state)


def test_a_new_run_can_start_after_the_previous_one_finished(client, emails, monkeypatch):
    fake_pipeline(monkeypatch)
    user = register(client, emails).json()

    first = client.post("/api/issues/generate-now", json={"user_id": user["id"]})
    second = client.post("/api/issues/generate-now", json={"user_id": user["id"]})

    assert first.status_code == second.status_code == 202


def test_second_run_is_refused_while_one_is_running(client, emails, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    user = register(client, emails).json()
    issues_api._runs[user["id"]] = {"state": "running"}

    response = client.post("/api/issues/generate-now", json={"user_id": user["id"]})

    assert response.status_code == 409
    assert calls["editorial"] == 0


def test_generate_now_refuses_unknown_inactive_and_topicless_users(client, emails, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    inactive = register(client, emails).json()
    client.patch(f"/api/users/{inactive['id']}/preferences", json={"is_active": False})
    topicless = register(client, emails, topics=[]).json()

    assert client.post("/api/issues/generate-now", json={"user_id": 99999999}).status_code == 404
    assert client.post("/api/issues/generate-now", json={"user_id": inactive["id"]}).status_code == 409
    assert client.post("/api/issues/generate-now", json={"user_id": topicless["id"]}).status_code == 409
    assert calls == {"research": 0, "editorial": 0}


def test_run_status_is_idle_before_any_run(client, emails):
    user = register(client, emails).json()

    assert client.get(f"/api/users/{user['id']}/run-status").json()["state"] == "idle"


# ------------------------------------------------------- issues and preview

def test_preview_returns_the_html_email(client, emails):
    user = register(client, emails).json()
    issue_id = make_issue(user["id"], html_body="<html><body><h1>Hi</h1></body></html>")

    response = client.get(f"/api/issues/{issue_id}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Hi</h1>" in response.text
    assert "script-src" not in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_preview_falls_back_to_escaped_plain_text(client, emails):
    user = register(client, emails).json()
    issue_id = make_issue(user["id"], html_body=None)
    with SessionLocal() as session:
        issue = session.get(NewsletterIssue, issue_id)
        issue.body = "<script>alert(1)</script> hello"
        session.commit()

    response = client.get(f"/api/issues/{issue_id}/preview")

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_unknown_issue_is_404(client):
    assert client.get("/api/issues/99999999").status_code == 404
    assert client.get("/api/issues/99999999/preview").status_code == 404


def test_issue_detail(client, emails):
    user = register(client, emails).json()
    issue_id = make_issue(user["id"])

    data = client.get(f"/api/issues/{issue_id}").json()

    assert data["subject"] == "Test subject"
    assert data["status"] == "approved"
    assert data["big_picture"] == "Big picture."
    assert data["editor_feedback"] == {"status": "approved", "issues": []}
    assert data["has_html"] is True
    assert data["preview_url"] == f"/api/issues/{issue_id}/preview"


def test_issue_list_is_newest_first_and_limited(client, emails):
    user = register(client, emails).json()
    ids = [make_issue(user["id"]) for _ in range(3)]

    listed = client.get(f"/api/users/{user['id']}/issues").json()
    limited = client.get(f"/api/users/{user['id']}/issues", params={"limit": 2}).json()

    assert [i["id"] for i in listed] == ids[::-1]
    assert len(limited) == 2


# ------------------------------------------------------------------ API key

def test_api_key_is_required_when_configured(client, emails, monkeypatch):
    user = register(client, emails).json()
    issue_id = make_issue(user["id"])
    monkeypatch.setattr(settings, "api_key", "s3cret")

    assert client.get(f"/api/users/{user['id']}/preferences").status_code == 401
    assert client.get(
        f"/api/users/{user['id']}/preferences", headers={"X-API-Key": "wrong"}
    ).status_code == 401
    assert client.get(
        f"/api/users/{user['id']}/preferences", headers={"X-API-Key": "s3cret"}
    ).status_code == 200
    # A plain browser link cannot send headers, so the query form works too.
    assert client.get(f"/api/issues/{issue_id}/preview").status_code == 401
    assert client.get(
        f"/api/issues/{issue_id}/preview", params={"api_key": "s3cret"}
    ).status_code == 200


def test_health_stays_open_when_an_api_key_is_set(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "s3cret")

    assert client.get("/health").status_code == 200


def test_api_is_open_when_no_key_is_configured(client, emails, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")

    assert register(client, emails).status_code == 201
