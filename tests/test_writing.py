import json
from unittest.mock import patch

import pytest
import requests

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


def test_rank_articles_uses_keywords_when_ai_returns_invalid_json(
    sample_articles,
):
    with patch(
        "app.agents.writing.get_chat_completion",
        return_value="not valid JSON",
    ) as mock_llm:
        result = rank_articles("AI", sample_articles)

    assert mock_llm.call_count == 2
    assert [a["title"] for a in result] == ["New AI model released"]


def test_rank_articles_uses_keywords_when_ai_is_unreachable(sample_articles):
    with patch(
        "app.agents.writing.get_chat_completion",
        side_effect=requests.Timeout("timed out"),
    ):
        result = rank_articles("AI", sample_articles)

    assert [a["title"] for a in result] == ["New AI model released"]


def test_rank_articles_does_not_hide_a_missing_api_key(sample_articles):
    with patch(
        "app.agents.writing.get_chat_completion",
        side_effect=RuntimeError("OPENROUTER_API_KEY is missing"),
    ):
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            rank_articles("AI", sample_articles)


def test_keyword_fallback_matches_whole_words_only():
    articles = [
        {"title": "Spain said it would maintain the plan", "summary": ""},
        {"title": "AI, explained", "summary": ""},
    ]

    with patch(
        "app.agents.writing.get_chat_completion",
        return_value="not valid JSON",
    ):
        result = rank_articles("AI", articles)

    assert [a["title"] for a in result] == ["AI, explained"]


def test_prepare_newsletter_content_skips_article_when_summary_fails(
    sample_articles,
):
    with patch(
        "app.agents.writing.get_chat_completion",
        side_effect=[
            '{"selected_ids": [0, 1], "reason": "Both"}',
            requests.Timeout("timed out"),
            "The team won an international match.",
        ],
    ):
        result = prepare_newsletter_content(
            topic="sports", articles=sample_articles, max_articles=2
        )

    assert len(result) == 1
    assert result[0]["title"] == "Cricket team wins match"


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


def test_ranking_prompt_uses_short_excerpts_and_enough_tokens():
    articles = [
        {
            "title": "New AI model",
            "summary": "A new model.",
            "content": "word " * 1000,
        }
    ]

    with patch(
        "app.agents.writing.get_chat_completion",
        return_value='{"selected_ids": [0], "reason": "ok"}',
    ) as mock_llm:
        rank_articles("AI", articles)

    user_prompt = mock_llm.call_args.args[1]
    sent_articles = json.loads(user_prompt.split("Articles:\n", 1)[1])

    assert len(sent_articles[0]["content_excerpt"]) <= 500
    assert mock_llm.call_args.kwargs["max_tokens"] >= 2000