from datetime import datetime, timezone

import pytest
import requests

from app.agents import curator
from app.agents.schemas import ArticleScore, CuratorOutput


def make_articles(count=6, **overrides):
    articles = []

    for index in range(count):
        article = {
            "id": 100 + index,
            "title": f"AI story {index}",
            "source_name": f"Source {index}",
            "summary": f"Summary {index}",
            "content": f"Full text {index}. " * 20,
            "published_at": datetime(2026, 10, 26, tzinfo=timezone.utc),
        }
        article.update(overrides)
        articles.append(article)

    return articles


def score(article_id, relevance=8, impact=8, credibility=8, novelty=8, **kw):
    return ArticleScore(
        article_id=article_id,
        relevance=relevance,
        impact=impact,
        credibility=credibility,
        novelty=novelty,
        **kw,
    )


def fake_llm(monkeypatch, scores):
    calls = []

    def fake(system_prompt, user_prompt, schema, **kwargs):
        calls.append({"user_prompt": user_prompt, "schema": schema})
        return CuratorOutput(scores=scores)

    monkeypatch.setattr(curator, "get_structured_completion", fake)
    return calls


def test_weighted_score_uses_design_weights():
    assert curator.weighted_score(10, 10, 10, 10) == pytest.approx(10)
    assert curator.weighted_score(10, 0, 0, 0) == pytest.approx(3.5)
    assert curator.weighted_score(0, 10, 0, 0) == pytest.approx(3.0)
    assert curator.weighted_score(0, 0, 10, 0) == pytest.approx(2.5)
    assert curator.weighted_score(0, 0, 0, 10) == pytest.approx(1.0)


def test_best_scored_articles_are_selected_in_order(monkeypatch):
    articles = make_articles(4)
    fake_llm(
        monkeypatch,
        [
            score(0, impact=5),
            score(1, impact=9),
            score(2, impact=7),
            score(3, impact=2),
        ],
    )

    selected = curator.curate_articles(articles, ["AI"], max_stories=3)

    assert [a["id"] for a in selected] == [101, 102, 100]
    assert all("curator_score" in a for a in selected)


def test_never_returns_more_than_max_stories(monkeypatch):
    articles = make_articles(8)
    fake_llm(monkeypatch, [score(i) for i in range(8)])

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert len(selected) == 5


def test_equal_scores_prefer_the_newer_earlier_article(monkeypatch):
    articles = make_articles(3)
    fake_llm(monkeypatch, [score(2), score(0), score(1)])

    selected = curator.curate_articles(articles, ["AI"], max_stories=2)

    assert [a["id"] for a in selected] == [100, 101]


def test_rejected_articles_are_excluded(monkeypatch):
    articles = make_articles(3)
    fake_llm(
        monkeypatch,
        [
            score(0),
            score(1, reject_reason="Promotional press release"),
            score(2),
        ],
    )

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert [a["id"] for a in selected] == [100, 102]


def test_low_relevance_is_excluded_even_with_high_other_scores(monkeypatch):
    articles = make_articles(2)
    fake_llm(
        monkeypatch,
        [
            score(0, relevance=3, impact=10, credibility=10, novelty=10),
            score(1, relevance=5, impact=5, credibility=5, novelty=5),
        ],
    )

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert [a["id"] for a in selected] == [101]


def test_few_eligible_articles_are_not_padded(monkeypatch):
    articles = make_articles(5)
    fake_llm(
        monkeypatch,
        [score(0), score(1, relevance=1)] + [score(i, relevance=0) for i in (2, 3, 4)],
    )

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert len(selected) == 1


def test_invented_and_repeated_ids_are_ignored(monkeypatch):
    articles = make_articles(2)
    fake_llm(
        monkeypatch,
        [score(0), score(0, impact=0), score(99), score(-1), score(1)],
    )

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert [a["id"] for a in selected] == [100, 101]
    # The first score for article 0 is kept, not the repeat.
    assert selected[0]["curator_score"] == pytest.approx(8.0)


def test_unscored_articles_are_not_selected(monkeypatch):
    articles = make_articles(3)
    fake_llm(monkeypatch, [score(1)])

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert [a["id"] for a in selected] == [101]


def test_trusted_source_gets_a_credibility_floor(monkeypatch):
    articles = make_articles(2)
    articles[1]["source_name"] = "Reuters"
    monkeypatch.setattr(curator.settings, "trusted_sources", "reuters, BBC")
    fake_llm(
        monkeypatch,
        [score(0, credibility=3), score(1, credibility=3)],
    )

    selected = curator.curate_articles(articles, ["AI"], max_stories=2)

    assert selected[0]["id"] == 101
    assert selected[0]["curator_score"] > selected[1]["curator_score"]


def test_limited_source_flag_and_excerpt_length(monkeypatch):
    articles = make_articles(2)
    articles[0]["content"] = "x" * 5000
    articles[1]["content"] = None
    calls = fake_llm(monkeypatch, [score(0), score(1)])

    selected = curator.curate_articles(articles, ["AI"], max_stories=2)

    assert selected[0]["limited_source"] is False
    assert selected[1]["limited_source"] is True
    assert "x" * 1001 not in calls[0]["user_prompt"]
    assert "x" * 1000 in calls[0]["user_prompt"]


def test_prompt_contains_topics_and_respects_candidate_limit(monkeypatch):
    articles = make_articles(30)
    monkeypatch.setattr(curator.settings, "curator_candidate_limit", 20)
    calls = fake_llm(monkeypatch, [score(0)])

    curator.curate_articles(articles, ["AI", "Cricket"], max_stories=3)

    assert "AI, Cricket" in calls[0]["user_prompt"]
    assert '"id": 19' in calls[0]["user_prompt"]
    assert '"id": 20' not in calls[0]["user_prompt"]


def test_empty_input_returns_empty_list_without_calling_ai(monkeypatch):
    calls = fake_llm(monkeypatch, [])

    assert curator.curate_articles([], ["AI"]) == []
    assert calls == []


def test_invalid_max_stories_is_rejected():
    with pytest.raises(ValueError, match="max_stories"):
        curator.curate_articles(make_articles(1), ["AI"], max_stories=0)


def test_input_articles_are_not_modified(monkeypatch):
    articles = make_articles(1)
    fake_llm(monkeypatch, [score(0)])

    curator.curate_articles(articles, ["AI"], max_stories=1)

    assert "curator_score" not in articles[0]


@pytest.mark.parametrize(
    "error",
    [ValueError("bad json"), requests.ConnectionError("down")],
)
def test_keyword_fallback_when_ai_fails(monkeypatch, error):
    articles = make_articles(3)
    articles[0]["title"] = "Cooking tips"
    articles[0]["summary"] = "Pasta"
    articles[1]["title"] = "AI chips"
    articles[2]["title"] = "Nothing relevant"
    articles[2]["summary"] = "Weather"

    def failing(*args, **kwargs):
        raise error

    monkeypatch.setattr(curator, "get_structured_completion", failing)

    selected = curator.curate_articles(articles, ["AI"], max_stories=5)

    assert [a["id"] for a in selected] == [101]
    assert selected[0]["curator_reason"] == "Selected by keyword fallback."


def test_missing_api_key_is_not_hidden(monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError("OPENROUTER_API_KEY is missing")

    monkeypatch.setattr(curator, "get_structured_completion", failing)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        curator.curate_articles(make_articles(2), ["AI"])
