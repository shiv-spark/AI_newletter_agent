
import uuid

from app.services.article_storage import save_articles
from app.database.db import SessionLocal
from app.database.models import Article
from sqlalchemy import select


def make_article():
    unique_id = uuid.uuid4().hex

    return {
        "topic": "AI",
        "title": f"Newsletter storage test {unique_id}",
        "url": f"https://example.com/news/{unique_id}",
        "source_name": "Example News",
        "published_at": None,
        "summary": f"Unique test content {unique_id}",
    }


def test_save_new_article():
    article = make_article()

    result = save_articles([article])

    assert result["inserted"] == 1
    assert result["skipped_duplicates"] == 0
    assert result["skipped_invalid"] == 0

    # Verify that the article really exists in PostgreSQL.
    with SessionLocal() as session:
        saved = session.scalar(
            select(Article).where(Article.url == article["url"])
        )
        assert saved is not None
        assert saved.title == article["title"]


def test_duplicate_url_is_skipped():
    article = make_article()

    first_result = save_articles([article])
    second_article = {
        **article,
        "url": article["url"] + "?utm_source=newsletter",
    }
    second_result = save_articles([second_article])

    assert first_result["inserted"] == 1
    assert second_result["inserted"] == 0
    assert second_result["skipped_duplicates"] == 1


def test_invalid_article_is_skipped():
    result = save_articles(
        [{"title": "Missing URL and source"}]
    )

    assert result["inserted"] == 0
    assert result["skipped_invalid"] == 1


def test_article_content_is_saved():
    article = make_article()
    article["content"] = "Full article text. " * 20

    save_articles([article])

    with SessionLocal() as session:
        saved = session.scalar(
            select(Article).where(Article.url == article["url"])
        )
        assert saved.content == article["content"].strip()
