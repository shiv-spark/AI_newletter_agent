
import pytest

from app.agents.deduplication import (
    generate_content_hash,
    normalize_url,
    remove_duplicate_articles,
)


def test_normalize_url_removes_tracking_parameters():
    url = (
        "https://www.example.com/article/"
        "?utm_source=newsletter&id=123#section"
    )

    assert normalize_url(url) == "https://example.com/article?id=123"


def test_normalize_url_rejects_invalid_url():
    with pytest.raises(ValueError):
        normalize_url("not-a-valid-url")


def test_content_hash_ignores_case_and_extra_spaces():
    first = generate_content_hash("AI News", "New model released")
    second = generate_content_hash(" ai NEWS ", "New   model released")

    assert first == second


def test_content_hash_rejects_empty_text():
    with pytest.raises(ValueError):
        generate_content_hash("", "  ")


def test_remove_duplicate_articles_by_url():
    articles = [
        {
            "title": "AI news",
            "url": "https://www.example.com/news?utm_source=email",
            "summary": "A new model was announced.",
        },
        {
            "title": "AI news",
            "url": "https://example.com/news#latest",
            "summary": "A new model was announced.",
        },
    ]

    result = remove_duplicate_articles(articles)

    assert len(result) == 1
    assert result[0]["canonical_url"] == "https://example.com/news"
    assert result[0]["content_hash"]


def test_remove_duplicate_articles_by_content():
    articles = [
        {
            "title": "New AI model",
            "url": "https://source-one.com/news",
            "summary": "A new model has been released.",
        },
        {
            "title": "New AI model",
            "url": "https://source-two.com/news",
            "summary": "A new model has been released.",
        },
    ]

    result = remove_duplicate_articles(articles)

    assert len(result) == 1


def test_articles_without_urls_are_skipped():
    result = remove_duplicate_articles(
        [{"title": "Article without URL", "summary": "Test"}]
    )

    assert result == []


def test_empty_batch_returns_empty_list():
    assert remove_duplicate_articles([]) == []
