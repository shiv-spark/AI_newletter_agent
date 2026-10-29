"""Optional API-key protection for the /api routes."""
import secrets

from fastapi import Header, HTTPException, Query

from app.config import settings


def require_api_key(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> None:
    """Allow the request only if it carries the configured API key.

    When API_KEY is empty the API is open (local development). A browser
    cannot send headers for a plain link, so the key may also be given as
    ?api_key=... (for example on the preview link).
    """
    expected = settings.api_key

    if not expected:
        return

    supplied = x_api_key or api_key or ""

    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
