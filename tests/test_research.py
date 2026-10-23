
from email.utils import formatdate

import pytest
import requests

from app.agents.research import (
    build_feed_url,
    collect_articles,
    fetch_articles_for_topic,
)


def test_build_feed_url():
    url = build_feed_url("Data Engineering")

    assert url.startswith("https://news.google.com/rss/search?")
    assert "Data" in url
    assert "Engineering" in url


def test_empty_topic_is_rejected():
    with pytest.raises(ValueError, match="Topic"):
        fetch_articles_for_topic("  ")


def test_invalid_max_results_is_rejected():
    with pytest.raises(ValueError, match="max_results"):
        fetch_articles_for_topic("AI", max_results=0)


def test_fetch_articles_for_topic(monkeypatch):
    published = formatdate(usegmt=True)

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test News</title>
        <item>
          <title>New AI research announced</title>
          <link>https://example.com/ai-news</link>
          <description>News about new AI research.</description>
          <pubDate>{published}</pubDate>
          <source>Example News</source>
        </item>
        <item>
          <title> </title>
          <link>https://example.com/invalid</link>
        </item>
      </channel>
    </rss>
    """.encode("utf-8")

    class FakeResponse:
        content = rss_xml

        def raise_for_status(self):
            pass

    def fake_get(*args, **kwargs):
        assert kwargs["timeout"] == 15
        return FakeResponse()

    monkeypatch.setattr(
        "app.agents.research.requests.get",
        fake_get,
    )

    articles = fetch_articles_for_topic("AI", max_results=5)

    assert len(articles) == 1
    assert articles[0]["topic"] == "AI"
    assert articles[0]["title"] == "New AI research announced"
    assert articles[0]["url"] == "https://example.com/ai-news"
    assert articles[0]["source_name"] == "Example News"
    assert articles[0]["published_at"] is not None
    assert "AI research" in articles[0]["summary"]


def test_http_error_is_raised(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.Timeout("Request timed out")

    monkeypatch.setattr(
        "app.agents.research.requests.get",
        fake_get,
    )

    with pytest.raises(requests.Timeout):
        fetch_articles_for_topic("AI")


def test_collect_articles_continues_after_failure(monkeypatch):
    def fake_fetch(topic, max_results):
        if topic == "AI":
            raise requests.Timeout("Request timed out")

        return [
            {
                "topic": topic,
                "title": "Snowflake update",
                "url": "https://example.com/snowflake",
                "source_name": "example.com",
                "published_at": None,
                "summary": "",
            }
        ]

    monkeypatch.setattr(
        "app.agents.research.fetch_articles_for_topic",
        fake_fetch,
    )

    articles = collect_articles(["AI", "Snowflake"])

    assert len(articles) == 1
    assert articles[0]["topic"] == "Snowflake"

