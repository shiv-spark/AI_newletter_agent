import pytest
from pydantic import ValidationError

from app.agents import analyst
from app.agents.schemas import AnalystOutput, StoryInsight


def make_stories(count=3):
    return [
        {
            "id": 500 + index,
            "title": f"Story {index}",
            "source_name": f"Source {index}",
            "summary": f"Summary {index}",
            "content": f"Full text {index}. " * 30,
        }
        for index in range(count)
    ]


def insight(article_id, **overrides):
    values = {
        "article_id": article_id,
        "what_happened": f"Happened {article_id}",
        "why_it_matters": f"Matters {article_id}",
        "impact": f"Impact {article_id}",
        "is_speculative": False,
    }
    values.update(overrides)
    return StoryInsight(**values)


def fake_llm(monkeypatch, outputs):
    """Return the given AnalystOutput objects one call at a time."""
    calls = []

    def fake(system_prompt, user_prompt, schema, **kwargs):
        calls.append({"user_prompt": user_prompt, "schema": schema})
        return outputs[len(calls) - 1]

    monkeypatch.setattr(analyst, "get_structured_completion", fake)
    return calls


def test_returns_big_picture_and_real_article_ids(monkeypatch):
    fake_llm(
        monkeypatch,
        [
            AnalystOutput(
                big_picture="Competition is rising.",
                stories=[insight(0), insight(1), insight(2)],
            )
        ],
    )

    result = analyst.analyze_stories(make_stories(3), ["AI"])

    assert result.big_picture == "Competition is rising."
    assert [s.article_id for s in result.stories] == [500, 501, 502]
    assert result.stories[1].what_happened == "Happened 1"


def test_insights_follow_the_input_order(monkeypatch):
    fake_llm(
        monkeypatch,
        [
            AnalystOutput(
                big_picture="Trend",
                stories=[insight(2), insight(0), insight(1)],
            )
        ],
    )

    result = analyst.analyze_stories(make_stories(3), ["AI"])

    assert [s.article_id for s in result.stories] == [500, 501, 502]
    assert result.stories[0].what_happened == "Happened 0"


def test_invented_ids_are_ignored(monkeypatch):
    fake_llm(
        monkeypatch,
        [
            AnalystOutput(
                big_picture="Trend",
                stories=[insight(0), insight(1), insight(99)],
            )
        ],
    )

    result = analyst.analyze_stories(make_stories(2), ["AI"])

    assert [s.article_id for s in result.stories] == [500, 501]


def test_missing_story_triggers_one_retry_with_feedback(monkeypatch):
    calls = fake_llm(
        monkeypatch,
        [
            AnalystOutput(big_picture="Trend", stories=[insight(0)]),
            AnalystOutput(
                big_picture="Trend", stories=[insight(0), insight(1)]
            ),
        ],
    )

    result = analyst.analyze_stories(make_stories(2), ["AI"])

    assert len(calls) == 2
    assert "Missing insights for story IDs [1]" in calls[1]["user_prompt"]
    assert [s.article_id for s in result.stories] == [500, 501]


def test_gives_up_when_stories_stay_missing(monkeypatch):
    incomplete = AnalystOutput(big_picture="Trend", stories=[insight(0)])
    calls = fake_llm(monkeypatch, [incomplete, incomplete])

    with pytest.raises(ValueError, match="did not cover every story"):
        analyst.analyze_stories(make_stories(2), ["AI"])

    assert len(calls) == 2


def test_limited_source_story_is_always_speculative(monkeypatch):
    stories = make_stories(2)
    stories[1]["content"] = None
    fake_llm(
        monkeypatch,
        [
            AnalystOutput(
                big_picture="Trend",
                stories=[insight(0), insight(1, is_speculative=False)],
            )
        ],
    )

    result = analyst.analyze_stories(stories, ["AI"])

    assert result.stories[0].is_speculative is False
    assert result.stories[1].is_speculative is True


def test_ai_speculative_flag_is_kept(monkeypatch):
    fake_llm(
        monkeypatch,
        [
            AnalystOutput(
                big_picture="Trend",
                stories=[insight(0, is_speculative=True)],
            )
        ],
    )

    result = analyst.analyze_stories(make_stories(1), ["AI"])

    assert result.stories[0].is_speculative is True


def test_prompt_has_topics_flags_and_truncated_excerpt(monkeypatch):
    stories = make_stories(2)
    stories[0]["content"] = "y" * 5000
    stories[1]["content"] = ""
    calls = fake_llm(
        monkeypatch,
        [
            AnalystOutput(
                big_picture="Trend", stories=[insight(0), insight(1)]
            )
        ],
    )

    analyst.analyze_stories(stories, ["AI", "Cricket"])

    prompt = calls[0]["user_prompt"]
    assert "AI, Cricket" in prompt
    assert "y" * 2000 in prompt
    assert "y" * 2001 not in prompt
    assert '"limited_source": true' in prompt
    assert '"limited_source": false' in prompt
    assert calls[0]["schema"] is AnalystOutput


def test_empty_story_list_is_rejected():
    with pytest.raises(ValueError, match="At least one story"):
        analyst.analyze_stories([], ["AI"])


def test_story_without_id_is_rejected():
    with pytest.raises(ValueError, match="must have an id"):
        analyst.analyze_stories([{"title": "No id"}], ["AI"])


def test_input_stories_are_not_modified(monkeypatch):
    stories = make_stories(1)
    snapshot = [dict(story) for story in stories]
    fake_llm(
        monkeypatch,
        [AnalystOutput(big_picture="Trend", stories=[insight(0)])],
    )

    analyst.analyze_stories(stories, ["AI"])

    assert stories == snapshot


def test_schema_rejects_empty_big_picture():
    with pytest.raises(ValidationError):
        AnalystOutput(big_picture="", stories=[insight(0)])
