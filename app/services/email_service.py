import requests

from app.config import settings


RESEND_API_URL = "https://api.resend.com/emails"


def send_email(to_email: str, subject: str, body: str) -> dict:
    """Send a plain-text email through Resend."""

    if not settings.resend_api_key:
        raise ValueError("RESEND_API_KEY is not configured.")

    if not settings.resend_from_email:
        raise ValueError("RESEND_FROM_EMAIL is not configured.")

    if not to_email or not to_email.strip():
        raise ValueError("Recipient email is required.")

    if not subject or not subject.strip():
        raise ValueError("Email subject is required.")

    if not body or not body.strip():
        raise ValueError("Email body is required.")

    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "from": settings.resend_from_email,
        "to": [to_email.strip()],
        "subject": subject.strip(),
        "text": body,
    }

    try:
        response = requests.post(
            RESEND_API_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )
    except requests.RequestException:
        return {
            "success": False,
            "error": "Could not connect to Resend. Check your network and try again.",
        }

    if not response.ok:
        return {
            "success": False,
            "error": f"Resend API returned HTTP {response.status_code}.",
        }

    try:
        response_data = response.json()
    except ValueError:
        return {
            "success": False,
            "error": "Resend returned an unexpected response.",
        }

    return {
        "success": True,
        "message_id": response_data.get("id"),
        "status": "accepted",
    }
