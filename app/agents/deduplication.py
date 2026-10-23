
import hashlib
import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)


TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
}

TRACKING_PREFIXES = ("utm_",)


def normalize_url(url: str) -> str:
    """Normalize a URL by removing common tracking parameters."""
    url = url.strip()

    if not url:
        raise ValueError("URL cannot be empty.")

    parts = urlsplit(url)

    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("A valid HTTP or HTTPS URL is required.")

    scheme = parts.scheme.lower()
    hostname = parts.hostname.lower()

    # Remove the default port from the URL.
    port = parts.port
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    # Treat www.example.com and example.com as the same host.
    if hostname.startswith("www."):
        hostname = hostname[4:]

    path = parts.path or "/"

    # Remove trailing slashes except for the root path.
    if path != "/":
        path = path.rstrip("/")

    query_parameters = []

    for key, value in parse_qsl(
        parts.query,
        keep_blank_values=True,
    ):
        normalized_key = key.lower()

        if normalized_key in TRACKING_PARAMETERS:
            continue

        if normalized_key.startswith(TRACKING_PREFIXES):
            continue

        query_parameters.append((key, value))

    query_parameters.sort()

    return urlunsplit(
        (
            scheme,
            hostname,
            path,
            urlencode(query_parameters),
            "",  # Ignore URL fragments.
        )
    )


def generate_content_hash(title: str, content: str = "") -> str:
    """Generate a stable hash from normalized article text."""
    normalized_text = f"{title} {content}".lower()
    normalized_text = re.sub(r"\s+", " ", normalized_text).strip()

    if not normalized_text:
        raise ValueError("Title and content cannot both be empty.")

    return hashlib.sha256(
        normalized_text.encode("utf-8")
    ).hexdigest()


def remove_duplicate_articles(
    articles: list[dict],
) -> list[dict]:
    """Remove duplicates within a collected batch.

    Articles must contain a URL. Title and summary are optional.
    The first occurrence is retained.
    """
    unique_articles = []
    seen_urls = set()
    seen_hashes = set()

    for article in articles:
        article_url = article.get("url", "").strip()

        if not article_url:
            continue

        canonical_url = normalize_url(article_url)

        title = article.get("title", "").strip()
        summary = article.get("summary", "").strip()

        content_hash = (
            generate_content_hash(title, summary)
            if title or summary
            else None
        )

        if canonical_url in seen_urls:
            continue

        if content_hash and content_hash in seen_hashes:
            continue

        cleaned_article = dict(article)
        cleaned_article["canonical_url"] = canonical_url
        cleaned_article["content_hash"] = content_hash

        unique_articles.append(cleaned_article)
        seen_urls.add(canonical_url)

        if content_hash:
            seen_hashes.add(content_hash)

    return unique_articles
