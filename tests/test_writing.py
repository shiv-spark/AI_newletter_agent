
from unittest.mock import patch

import pytest

from app.agents.writing import (
    rank_articles,
    summarize_article,
    prepare_newsletter_content,
)


@pytest.fixture
def sample_articles():
    return [
        {
            "title": "New AI model released",
            "summary": "A company released a new AI model.",
            "source_name": "Tech News",
            "url": "https://example.com/ai",
        },
        {
            "title": "Cricket team wins match",
            "summary": "The team won an international match.",
            "source_name": "Sports News",
            "url": "https://example.com/cricket",
        },
    ]


def test_rank_articles_returns_selected_articles(sample_articles):
    with patch(
        "app.agents.writing.get_chat_completion",
        return_value='{"selected_ids": [0], "reason": "Relevant"}',
    ):
        result = rank_articles("AI", sample_articles, max_articles=1)

    assert len(result) == 1
    assert result[0]["title"] == "New AI model released"


def test_rank_articles_empty_input():
    assert rank_articles("AI", []) == []


def test_rank_articles_rejects_invalid_json(sample_articles):
    with patch(
        "app.agents.writing.get_chat_completion",
        return_value="not valid JSON",
    ):
        with pytest.raises(ValueError, match="invalid article-ranking"):
            rank_articles("AI", sample_articles)


def test_summarize_article(sample_articles):
    with patch(
        "app.agents.writing.get_chat_completion",
        return_value="A new AI model has been released.",
    ):
        result = summarize_article(sample_articles[0])

    assert result == "A new AI model has been released."


def test_summarize_article_requires_title():
    with pytest.raises(ValueError, match="title is required"):
        summarize_article({"summary": "Some description"})


def test_prepare_newsletter_content(sample_articles):
    with patch(
        "app.agents.writing.get_chat_completion",
        side_effect=[
            '{"selected_ids": [0], "reason": "Relevant"}',
            "A company released a new AI model.",
        ],
    ):
        result = prepare_newsletter_content(
            topic="AI",
            articles=sample_articles,
            max_articles=1,
        )

    assert len(result) == 1
    assert result[0]["title"] == "New AI model released"
    assert result[0]["ai_summary"] == "A company released a new AI model."
