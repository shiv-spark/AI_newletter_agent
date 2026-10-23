
from app.agents.research import collect_articles
from app.agents.deduplication import remove_duplicate_articles
from app.services.article_storage import save_articles


def run_research_pipeline(
    topics: list[str],
    max_results_per_topic: int = 10,
) -> dict:
    """Collect articles, remove batch duplicates, and save new records."""

    if max_results_per_topic < 1:
        raise ValueError("max_results_per_topic must be at least 1.")

    valid_topics = [
        topic.strip()
        for topic in topics
        if topic and topic.strip()
    ]

    # Stage 1: Collect RSS articles.
    collected = collect_articles(
        topics=valid_topics,
        max_results_per_topic=max_results_per_topic,
    )

    # Stage 2: Remove duplicates within this batch.
    unique_articles = remove_duplicate_articles(collected)

    # Stage 3: Save only new articles to PostgreSQL.
    storage_result = save_articles(unique_articles)

    return {
        "topics_requested": len(valid_topics),
        "articles_collected": len(collected),
        "articles_after_batch_deduplication": len(unique_articles),
        **storage_result,
    }
