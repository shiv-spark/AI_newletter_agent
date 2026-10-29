import pytest

from app.services import email_service


class FakeResponse:
    ok = True
    status_code = 200

    def json(self):
        return {"id": "msg-1"}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "key")
    monkeypatch.setattr(
        email_service.settings, "resend_from_email", "news@example.com"
    )


def capture_post(monkeypatch):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["json"] = json
        return FakeResponse()

    monkeypatch.setattr(email_service.requests, "post", fake_post)
    return sent


def test_plain_text_only_email_has_no_html_part(configured, monkeypatch):
    sent = capture_post(monkeypatch)

    result = email_service.send_email("a@example.com", "Subject", "Body")

    assert result["success"] is True
    assert sent["json"]["text"] == "Body"
    assert "html" not in sent["json"]


def test_html_part_is_sent_next_to_plain_text(configured, monkeypatch):
    sent = capture_post(monkeypatch)

    email_service.send_email(
        "a@example.com", "Subject", "Plain body", html="<p>Rich body</p>"
    )

    assert sent["json"]["html"] == "<p>Rich body</p>"
    assert sent["json"]["text"] == "Plain body"
    assert sent["json"]["to"] == ["a@example.com"]


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_html_is_not_sent(configured, monkeypatch, blank):
    sent = capture_post(monkeypatch)

    email_service.send_email("a@example.com", "S", "Body", html=blank)

    assert "html" not in sent["json"]


def test_body_is_still_required_when_html_is_given(configured):
    with pytest.raises(ValueError, match="body"):
        email_service.send_email("a@example.com", "S", "  ", html="<p>x</p>")


def test_missing_api_key_is_reported(monkeypatch):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "")

    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        email_service.send_email("a@example.com", "S", "Body")
