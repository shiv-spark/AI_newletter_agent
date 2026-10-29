import json

import pytest

from app.agents import editor
from app.agents.schemas import (
    EditorIssue,
    EditorVerdict,
    WriterOutput,
    WrittenStory,
)


# ---------------------------------------------------------------- helpers

def make_sources(count=4):
    return [
        {
            "id": 900 + index,
            "title": f"Story {index}",
            "source_name": f"Source {index}",
            "summary": f"Summary {index}",
            "content": "The startup raised 50 million dollars. " * 10,
        }
        for index in range(count)
    ]


def written(article_id, what_happened="First point. Second point.", **kw):
    values = {
        "article_id": article_id,
        "headline": f"Headline {article_id}",
        "what_happened": what_happened,
        "why_it_matters": "It matters.",
        "key_fact": None,
    }
    values.update(kw)
    return WrittenStory(**values)


def make_output(count=4, subject="Weekly update"):
    return WriterOutput(
        subject=subject,
        stories=[written(900 + i) for i in range(count)],
    )


def issue(article_id, problem="Wrong number.", correction="Use 50 million."):
    return EditorIssue(
        article_id=article_id, problem=problem, correction=correction
    )


def approved():
    return EditorVerdict(status="approved")


def rejected(*issues):
    return EditorVerdict(status="rejected", issues=list(issues))


def fake_review_llm(monkeypatch, verdicts):
    calls = []

    def fake(system_prompt, user_prompt, schema, **kwargs):
        calls.append(
            {"prompt": user_prompt, "schema": schema, "kwargs": kwargs}
        )
        return verdicts[len(calls) - 1]

    monkeypatch.setattr(editor, "get_structured_completion", fake)
    return calls


# --------------------------------------------------------- review_newsletter

def test_clean_newsletter_is_approved(monkeypatch):
    fake_review_llm(monkeypatch, [approved()])

    verdict = editor.review_newsletter(
        make_sources(1), "Subject", [written(900)]
    )

    assert verdict.status == "approved"
    assert verdict.issues == []


def test_issue_ids_are_mapped_to_real_article_ids(monkeypatch):
    fake_review_llm(monkeypatch, [rejected(issue(1), issue(None))])

    verdict = editor.review_newsletter(
        make_sources(2), "Subject", [written(900), written(901)]
    )

    assert verdict.status == "rejected"
    assert [i.article_id for i in verdict.issues] == [901, None]


def test_unknown_issue_id_becomes_a_subject_level_issue(monkeypatch):
    fake_review_llm(monkeypatch, [rejected(issue(42))])

    verdict = editor.review_newsletter(
        make_sources(1), "Subject", [written(900)]
    )

    assert verdict.issues[0].article_id is None


def test_approved_with_issues_is_turned_into_rejected(monkeypatch):
    fake_review_llm(
        monkeypatch,
        [EditorVerdict(status="approved", issues=[issue(0)])],
    )

    verdict = editor.review_newsletter(
        make_sources(1), "Subject", [written(900)]
    )

    assert verdict.status == "rejected"


def test_needs_review_is_preserved(monkeypatch):
    fake_review_llm(monkeypatch, [EditorVerdict(status="needs_review")])

    verdict = editor.review_newsletter(
        make_sources(1), "Subject", [written(900)]
    )

    assert verdict.status == "needs_review"


def test_wrong_sentence_count_is_caught_by_code(monkeypatch):
    fake_review_llm(monkeypatch, [approved()])

    verdict = editor.review_newsletter(
        make_sources(1),
        "Subject",
        [written(900, "Only one sentence here.")],
    )

    assert verdict.status == "rejected"
    assert verdict.issues[0].article_id == 900
    assert "exactly two sentences" in verdict.issues[0].correction


def test_unsupported_key_fact_is_caught_by_code(monkeypatch):
    fake_review_llm(monkeypatch, [approved()])

    verdict = editor.review_newsletter(
        make_sources(1),
        "Subject",
        [written(900, key_fact="Raised 500 million dollars")],
    )

    assert verdict.status == "rejected"
    assert "key fact" in verdict.issues[0].problem


def test_supported_key_fact_passes(monkeypatch):
    fake_review_llm(monkeypatch, [approved()])

    verdict = editor.review_newsletter(
        make_sources(1),
        "Subject",
        [written(900, key_fact="Raised 50 million dollars")],
    )

    assert verdict.status == "approved"


def test_prompt_contains_source_text_and_newsletter_text(monkeypatch):
    sources = make_sources(2)
    sources[0]["content"] = "q" * 5000
    sources[1]["content"] = ""
    calls = fake_review_llm(monkeypatch, [approved()])

    editor.review_newsletter(
        sources,
        "My subject",
        [written(900), written(901)],
        language="hi",
    )

    prompt = calls[0]["prompt"]
    assert "Subject line: My subject" in prompt
    assert "Newsletter language: hi" in prompt
    assert "q" * 3000 in prompt and "q" * 3001 not in prompt
    assert '"limited_source": true' in prompt
    assert "Headline 900" in prompt
    assert calls[0]["schema"] is EditorVerdict


def test_editor_model_setting_is_used(monkeypatch):
    calls = fake_review_llm(monkeypatch, [approved(), approved()])

    monkeypatch.setattr(editor.settings, "openrouter_editor_model", "big/model")
    editor.review_newsletter(make_sources(1), "S", [written(900)])
    monkeypatch.setattr(editor.settings, "openrouter_editor_model", "")
    editor.review_newsletter(make_sources(1), "S", [written(900)])

    assert calls[0]["kwargs"]["model"] == "big/model"
    assert calls[1]["kwargs"]["model"] is None


def test_review_rejects_bad_input():
    with pytest.raises(ValueError, match="At least one written story"):
        editor.review_newsletter(make_sources(1), "S", [])

    with pytest.raises(ValueError, match="No source article"):
        editor.review_newsletter(make_sources(1), "S", [written(12345)])


# ---------------------------------------------------------- review_and_revise

class Loop:
    """Scripted reviews plus a recorder for Writer revisions."""

    def __init__(self, monkeypatch, verdicts):
        self.verdicts = list(verdicts)
        self.reviews = []
        self.story_revisions = []
        self.subject_revisions = []

        def fake_review(stories, subject, written_stories, language="en"):
            self.reviews.append(
                {
                    "subject": subject,
                    "stories": [dict(s.model_dump()) for s in written_stories],
                }
            )
            return self.verdicts[len(self.reviews) - 1]

        def fake_revise_story(story, current, issues, language="en"):
            self.story_revisions.append((current.article_id, list(issues)))
            return current.model_copy(
                update={"headline": current.headline + " (revised)"}
            )

        def fake_revise_subject(subject, issues, headlines, language="en"):
            self.subject_revisions.append(list(issues))
            return subject + " (revised)"

        monkeypatch.setattr(editor, "review_newsletter", fake_review)
        monkeypatch.setattr(editor, "revise_story", fake_revise_story)
        monkeypatch.setattr(editor, "revise_subject", fake_revise_subject)


def test_approved_first_time_needs_no_revision(monkeypatch):
    loop = Loop(monkeypatch, [approved()])

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "approved"
    assert result.revision_count == 0
    assert len(loop.reviews) == 1
    assert loop.story_revisions == []
    assert len(result.stories) == 4


def test_rejected_story_is_revised_and_then_approved(monkeypatch):
    loop = Loop(monkeypatch, [rejected(issue(901)), approved()])

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "approved"
    assert result.revision_count == 1
    assert [story_id for story_id, _ in loop.story_revisions] == [901]
    assert loop.story_revisions[0][1][0].correction == "Use 50 million."
    headlines = {s.article_id: s.headline for s in result.stories}
    assert headlines[901] == "Headline 901 (revised)"
    assert headlines[900] == "Headline 900"
    # The second review saw the revised text.
    assert "(revised)" in json.dumps(loop.reviews[1]["stories"])


def test_second_correction_attempt_is_allowed(monkeypatch):
    loop = Loop(
        monkeypatch, [rejected(issue(900)), rejected(issue(900)), approved()]
    )

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "approved"
    assert result.revision_count == 2
    assert len(loop.reviews) == 3
    assert result.dropped_article_ids == []
    assert result.big_picture_stale is False


def test_never_more_than_two_revision_rounds(monkeypatch):
    loop = Loop(monkeypatch, [rejected(issue(900))] * 5)

    editor.review_and_revise(make_sources(), make_output())

    assert len(loop.reviews) == 3
    assert len(loop.story_revisions) == 2


def test_story_failing_every_round_is_dropped(monkeypatch):
    Loop(monkeypatch, [rejected(issue(902))] * 3)

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "approved"
    assert result.dropped_article_ids == [902]
    assert [s.article_id for s in result.stories] == [900, 901, 903]
    assert result.big_picture_stale is True


def test_too_few_stories_left_means_rejected(monkeypatch):
    Loop(
        monkeypatch,
        [rejected(issue(900), issue(901))] * 3,
    )

    result = editor.review_and_revise(
        make_sources(), make_output(), min_stories=3
    )

    assert result.status == "rejected"
    assert result.dropped_article_ids == [900, 901]
    assert "required" in result.note


def test_subject_issue_is_revised(monkeypatch):
    loop = Loop(monkeypatch, [rejected(issue(None)), approved()])

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "approved"
    assert len(loop.subject_revisions) == 1
    assert result.subject == "Weekly update (revised)"


def test_subject_that_never_passes_means_rejected(monkeypatch):
    Loop(monkeypatch, [rejected(issue(None))] * 3)

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "rejected"
    assert "subject" in result.note


def test_needs_review_stops_without_revising(monkeypatch):
    loop = Loop(monkeypatch, [EditorVerdict(status="needs_review")])

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "needs_review"
    assert len(loop.reviews) == 1
    assert loop.story_revisions == []


def test_editor_failure_is_never_approved(monkeypatch):
    def failing(*args, **kwargs):
        raise ValueError("AI did not return valid EditorVerdict")

    monkeypatch.setattr(editor, "review_newsletter", failing)

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "needs_review"
    assert "could not produce a verdict" in result.note


def test_missing_api_key_is_not_hidden(monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError("OPENROUTER_API_KEY is missing")

    monkeypatch.setattr(editor, "review_newsletter", failing)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        editor.review_and_revise(make_sources(), make_output())


def test_failed_revision_does_not_crash_the_loop(monkeypatch):
    Loop(monkeypatch, [rejected(issue(900))] * 3)

    def broken(*args, **kwargs):
        raise ValueError("AI did not return valid WrittenStory")

    monkeypatch.setattr(editor, "revise_story", broken)

    result = editor.review_and_revise(make_sources(), make_output())

    assert result.status == "approved"
    assert result.dropped_article_ids == [900]


def test_zero_revisions_means_straight_to_drop(monkeypatch):
    loop = Loop(monkeypatch, [rejected(issue(900))])

    result = editor.review_and_revise(
        make_sources(), make_output(), max_revisions=0
    )

    assert len(loop.reviews) == 1
    assert loop.story_revisions == []
    assert result.dropped_article_ids == [900]
    assert result.revision_count == 0


def test_default_revision_limit_comes_from_settings(monkeypatch):
    monkeypatch.setattr(editor.settings, "max_correction_attempts", 1)
    loop = Loop(monkeypatch, [rejected(issue(900))] * 5)

    editor.review_and_revise(make_sources(), make_output())

    assert len(loop.reviews) == 2


def test_feedback_json_is_valid_and_complete(monkeypatch):
    Loop(monkeypatch, [rejected(issue(900)), approved()])

    result = editor.review_and_revise(make_sources(), make_output())
    data = json.loads(result.feedback_json())

    assert data["status"] == "approved"
    assert data["revision_count"] == 1
    assert len(data["history"]) == 2
    assert data["history"][0]["issues"][0]["article_id"] == 900


def test_input_output_object_is_not_modified(monkeypatch):
    Loop(monkeypatch, [rejected(issue(900)), approved()])
    output = make_output()
    snapshot = output.model_dump()

    editor.review_and_revise(make_sources(), output)

    assert output.model_dump() == snapshot


def test_negative_max_revisions_is_rejected():
    with pytest.raises(ValueError, match="cannot be negative"):
        editor.review_and_revise(
            make_sources(), make_output(), max_revisions=-1
        )


def test_story_without_source_is_rejected():
    with pytest.raises(ValueError, match="No source article"):
        editor.review_and_revise(make_sources(1), make_output(2))
