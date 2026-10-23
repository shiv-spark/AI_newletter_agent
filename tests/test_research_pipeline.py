
import pytest

from app.services.research_pipeline import run_research_pipeline


def test_pipeline_collects_deduplicates_and_saves(monkeypatch):
    articles = [
        {
            "topic": "AI",
            "title": "New AI model",
            "url": "https://example.com/news?utm_source=email",
            "source_name": "Example News",
            "published_at": None,
            "summary": "A new model was released.",
        },
        {
            "topic": "AI",
            "title": "New AI model",
            "url": "https://example.com/news",
            "source_name": "Example News",
            "published_at": None,
            "summary": "A new model was released.",
        },
    ]

    def fake_collect(topics, max_results_per_topic):
        assert topics == ["AI", "Data Engineering"]
        assert max_results_per_topic == 5
        return articles

    def fake_save(unique_articles):
        assert len(unique_articles) == 1
        assert unique_articles[0]["canonical_url"] == (
            "https://example.com/news"
        )
        return {
            "inserted": 1,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
        }

    monkeypatch.setattr(
        "app.services.research_pipeline.collect_articles",
        fake_collect,
    )
    monkeypatch.setattr(
        "app.services.research_pipeline.save_articles",
        fake_save,
    )

    result = run_research_pipeline(
        ["AI", "Data Engineering"],
        max_results_per_topic=5,
    )

    assert result == {
        "topics_requested": 2,
        "articles_collected": 2,
        "articles_after_batch_deduplication": 1,
        "inserted": 1,
        "skipped_duplicates": 0,
        "skipped_invalid": 0,
    }


def test_pipeline_handles_empty_topics(monkeypatch):
    monkeypatch.setattr(
        "app.services.research_pipeline.save_articles",
        lambda articles: {
            "inserted": 0,
            "skipped_duplicates": 0,
            "skipped_invalid": 0,
        },
    )

    result = run_research_pipeline([])

    assert result["topics_requested"] == 0
    assert result["articles_collected"] == 0
    assert result["inserted"] == 0


def test_pipeline_rejects_invalid_limit():
    with pytest.raises(ValueError, match="max_results_per_topic"):
        run_research_pipeline(["AI"], max_results_per_topic=0)
