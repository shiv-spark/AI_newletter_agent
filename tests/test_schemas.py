import pytest
from pydantic import ValidationError

from app.agents.schemas import (
    AnalystOutput,
    ArticleScore,
    CuratorOutput,
    EditorVerdict,
    WrittenStory,
    WriterOutput,
)


def test_article_score_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        ArticleScore(
            article_id=1, relevance=11, impact=5, credibility=5, novelty=5
        )


def test_curator_output_accepts_valid_scores():
    output = CuratorOutput.model_validate(
        {
            "scores": [
                {
                    "article_id": 1,
                    "relevance": 9,
                    "impact": 8,
                    "credibility": 7,
                    "novelty": 6,
                }
            ]
        }
    )
    assert output.scores[0].article_id == 1


def test_analyst_requires_big_picture_and_stories():
    with pytest.raises(ValidationError):
        AnalystOutput.model_validate({"big_picture": "", "stories": []})


def test_analyst_rejects_duplicate_article_ids():
    story = {
        "article_id": 1,
        "what_happened": "A",
        "why_it_matters": "B",
        "impact": "C",
    }
    with pytest.raises(ValidationError):
        AnalystOutput.model_validate(
            {"big_picture": "Trend", "stories": [story, story]}
        )


def test_writer_blank_key_fact_becomes_none():
    output = WriterOutput.model_validate(
        {
            "subject": "Weekly AI update",
            "stories": [
                {
                    "article_id": 1,
                    "headline": "H",
                    "what_happened": "One. Two.",
                    "why_it_matters": "Because.",
                    "key_fact": "   ",
                }
            ],
        }
    )
    assert output.stories[0].key_fact is None


def test_editor_rejected_verdict_needs_issues():
    with pytest.raises(ValidationError):
        EditorVerdict(status="rejected", issues=[])


def test_editor_rejects_unknown_status():
    with pytest.raises(ValidationError):
        EditorVerdict(status="maybe")


def test_editor_approved_without_issues_is_valid():
    assert EditorVerdict(status="approved").issues == []


def test_numeric_key_fact_becomes_text():
    story = WrittenStory(
        article_id=1,
        headline="H",
        what_happened="One. Two.",
        why_it_matters="M",
        key_fact=450000000,
    )

    assert story.key_fact == "450000000"