from app.agents.research import clean_summary,resolve_article_url
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.database.db import SessionLocal
from app.database.models import Article
from app.agents.deduplication import (
    generate_content_hash,
    normalize_url,
)


def save_articles(articles: list[dict]) -> dict:
    """Save new articles and skip historical duplicates.

    Returns counts for inserted, duplicate and invalid articles.
    """
    result = {
        "inserted": 0,
        "skipped_duplicates": 0,
        "skipped_invalid": 0,
    }

    with SessionLocal() as session:
        for item in articles:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            source_name = (item.get("source_name") or "").strip()
            summary = clean_summary(item.get("summary") or "")
            content = (item.get("content") or "").strip() or None
            if not title or not url or not source_name:
                result["skipped_invalid"] += 1
                continue

            try:
                url = resolve_article_url(url)
                canonical_url = normalize_url(url)
                content_hash = generate_content_hash(title, summary)
            except ValueError:
                result["skipped_invalid"] += 1
                continue

            existing = session.scalar(
                select(Article.id).where(
                    or_(
                        Article.url == url,
                        Article.canonical_url == canonical_url,
                        Article.content_hash == content_hash,
                    )
                ).limit(1)
            )

            if existing is not None:
                result["skipped_duplicates"] += 1
                continue

            article = Article(
                title=title,
                url=url,
                canonical_url=canonical_url,
                source_name=source_name,
                published_at=item.get("published_at"),
                content_hash=content_hash,
                summary=summary or None,
                
            )

            session.add(article)

            try:
                session.commit()
                result["inserted"] += 1
            except IntegrityError:
                # Another operation may have inserted the same URL.
                session.rollback()
                result["skipped_duplicates"] += 1

    return result
