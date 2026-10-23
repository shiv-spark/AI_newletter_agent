import re
from html import unescape
from datetime import datetime, timezone
from unittest import result
from urllib.parse import quote
from urllib.parse import urlparse
import trafilatura
import feedparser
import requests
from googlenewsdecoder import new_decoderv1
import trafilatura


GOOGLE_NEWS_RSS_URL = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)


def build_feed_url(topic: str) -> str:
    """Build an RSS search URL for a topic."""
    query = quote(topic)
    return GOOGLE_NEWS_RSS_URL.format(query=query)

def resolve_article_url(article_url: str) -> str:
    """Resolve Google News URLs to the original publisher URL."""
    if not article_url:
        return article_url

    if "news.google.com" not in urlparse(article_url).netloc.lower():
        return article_url

    try:
        result = new_decoderv1(article_url)

        if result.get("status"):
            decoded_url = result.get("decoded_url", "")

            if decoded_url.startswith(("https://", "http://")):
                return decoded_url

    except Exception as exc:
        print(f"Could not decode Google News URL: {exc}")

    # Keep the original URL if decoding fails.
    return article_url

def parse_published_date(entry) -> datetime | None:
    """Convert an RSS publication date into a timezone-aware datetime."""
    published = entry.get("published_parsed")

    if published is None:
        return None

    return datetime(
        *published[:6],
        tzinfo=timezone.utc,
    )


def extract_source_name(entry, article_url: str) -> str:
    """Extract the publisher name, falling back to the URL hostname."""
    source = entry.get("source", {})
    source_name = source.get("title") if source else None

    if source_name:
        return source_name.strip()

    return urlparse(article_url).hostname or "Unknown source"

def clean_summary(summary: str) -> str:
    """Remove HTML tags and normalize RSS summary text."""
    if not summary:
        return ""

    text = re.sub(r"<[^>]+>", " ", summary)
    text = unescape(text)

    return " ".join(text.split())

def extract_article_content(
    article_url: str,
    min_length: int = 300,
) -> dict:
    """Extract readable article text without modifying the database."""

    result = {
        "content": "",
        "final_url": article_url,
        "status": "not_extracted",
    }

    if not article_url or not article_url.startswith(("http://", "https://")):
        result["status"] = "invalid_url"
        return result

    article_url = resolve_article_url(article_url)
    result["final_url"] = article_url

    try:
        response = requests.get(
            article_url,
            timeout=15,
            headers={
                "User-Agent": "AINewsletterAgent/1.0"
            },
            allow_redirects=True,
        )
        response.raise_for_status()

        result["final_url"] = response.url

        content = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )

        if not content:
            result["status"] = "no_content"
            return result

        content = " ".join(content.split())

        if len(content) < min_length:
            result["status"] = "insufficient_content"
            return result

        result["content"] = content
        result["status"] = "success"
        return result

    except requests.RequestException:
        result["status"] = "fetch_failed"
        return result
    except Exception:
        result["status"] = "extraction_failed"
        return result

def fetch_articles_for_topic(
    topic: str,
    max_results: int = 10,
) -> list[dict]:
    """Fetch and normalize RSS articles for one topic."""
    topic = topic.strip()

    if not topic:
        raise ValueError("Topic cannot be empty.")

    if max_results < 1:
        raise ValueError("max_results must be at least 1.")

    feed_url = build_feed_url(topic)

    response = requests.get(
        feed_url,
        timeout=15,
        headers={"User-Agent": "AINewsletterAgent/1.0"},
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    articles = []

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        article_url = entry.get("link", "").strip()

        if not title or not article_url:
            continue
        resolved_url = resolve_article_url(article_url)
        extracted = extract_article_content(resolved_url)
        articles.append(
            {
                "topic": topic,
                "title": title,
                "url": resolved_url,
                "source_name": extract_source_name(entry, resolved_url),
                "published_at": parse_published_date(entry),
                "summary": clean_summary(entry.get("summary", "")),
                "content": (
                    extracted["content"]
                    if extracted["status"] == "success"
                    else None
                ),
            }
        )

        if len(articles) >= max_results:
            break

    return articles


def collect_articles(
    topics: list[str],
    max_results_per_topic: int = 10,
) -> list[dict]:
    """Collect articles for multiple topics."""
    if not topics:
        return []

    collected_articles = []

    for topic in topics:
        if not topic or not topic.strip():
            continue

        try:
            articles = fetch_articles_for_topic(
                topic=topic,
                max_results=max_results_per_topic,
            )
            collected_articles.extend(articles)
        except (requests.RequestException, ValueError) as exc:
            # A failed topic should not stop collection for other topics.
            print(f"Could not collect news for '{topic}': {exc}")

    return collected_articles
