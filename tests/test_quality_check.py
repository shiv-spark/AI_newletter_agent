
from app.agents.quality_check import validate_newsletter


def sample_article(article_id=1):
    return {
        "id": article_id,
        "title": "New AI data platform released",
        "url": "https://example.com/ai-news",
        "source_name": "Example News",
        "ai_summary": "A new platform aims to simplify data processing.",
    }


def test_valid_newsletter_passes():
    result = validate_newsletter(
        subject="Your AI Newsletter",
        body="Here are today's top AI stories.",
        articles=[sample_article()],
    )

    assert result["passed"] is True
    assert result["errors"] == []
    assert result["article_count"] == 1


def test_empty_subject_fails():
    result = validate_newsletter(
        subject=" ",
        body="Newsletter content",
        articles=[sample_article()],
    )

    assert result["passed"] is False
    assert any("subject" in error.lower() for error in result["errors"])


def test_empty_body_fails():
    result = validate_newsletter(
        subject="AI Newsletter",
        body="",
        articles=[sample_article()],
    )

    assert result["passed"] is False
    assert any("body" in error.lower() for error in result["errors"])


def test_empty_articles_fail():
    result = validate_newsletter(
        subject="AI Newsletter",
        body="Newsletter content",
        articles=[],
    )

    assert result["passed"] is False
    assert any("at least one article" in error for error in result["errors"])


def test_duplicate_article_ids_fail():
    result = validate_newsletter(
        subject="AI Newsletter",
        body="Newsletter content",
        articles=[sample_article(1), sample_article(1)],
    )

    assert result["passed"] is False
    assert any("Duplicate article ID" in error for error in result["errors"])


def test_invalid_url_fails():
    article = sample_article()
    article["url"] = "ftp://example.com/ai-news"

    result = validate_newsletter(
        subject="AI Newsletter",
        body="Newsletter content",
        articles=[article],
    )

    assert result["passed"] is False
    assert any("invalid HTTP/HTTPS URL" in error for error in result["errors"])


def test_missing_summary_fails():
    article = sample_article()
    article["ai_summary"] = ""

    result = validate_newsletter(
        subject="AI Newsletter",
        body="Newsletter content",
        articles=[article],
    )

    assert result["passed"] is False
    assert any("AI summary" in error for error in result["errors"])


def test_missing_source_is_warning():
    article = sample_article()
    article["source_name"] = ""

    result = validate_newsletter(
        subject="AI Newsletter",
        body="Newsletter content",
        articles=[article],
    )

    assert result["passed"] is True
    assert len(result["warnings"]) == 1
