"""Generate and verify secure tamper-proof tokens for email actions like unsubscribe."""
import hashlib
import hmac

from app.config import settings


def _secret_key() -> bytes:
    key = settings.api_key or "ai-newsletter-subscription-secret"
    return key.encode("utf-8")


def generate_user_token(user_id: int) -> str:
    """Generate a signed, tamper-proof token for a user."""
    message = str(user_id).encode("utf-8")
    sig = hmac.new(_secret_key(), message, hashlib.sha256).hexdigest()[:24]
    return f"{user_id}.{sig}"


def verify_user_token(token: str) -> int | None:
    """Verify the token signature and return the user_id, or None if invalid."""
    if not token or "." not in token:
        return None

    user_id_str, sig = token.split(".", 1)
    if not user_id_str.isdigit():
        return None

    user_id = int(user_id_str)
    expected_sig = hmac.new(
        _secret_key(), user_id_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:24]

    if hmac.compare_digest(sig, expected_sig):
        return user_id

    return None
