import pytest

from app.agents import writer
from app.agents.schemas import (
    AnalystOutput,
    EditorIssue,
    StoryInsight,
    SubjectRevision,
    WriterOutput,
    WrittenStory,
)


# ---------------------------------------------------------------- helpers

def make_stories(count=2):
    return [
        {
            "id": 700 + index,
            "title": f"Story {index}",
            "source_name": f"Source {index}",
            "summary": f"Summary {index}",
            "content": f"Company raised 50 million dollars in round {index}. " * 10,
        }
        for index in range(count)
    ]


def make_analysis(stories):
    return AnalystOutput(
        big_picture="Competition is rising.",
        stories=[
            StoryInsight(
                article_id=story["id"],
                what_happened="Happened",
                why_it_matters="Matters",
                impact="Impact",
                is_speculative=(index == 1),
            )
            for index, story in enumerate(stories)
        ],
    )


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


def fake_llm(monkeypatch, outputs):
    calls = []

    def fake(system_prompt, user_prompt, schema, **kwargs):
        calls.append({"prompt": user_prompt, "schema": schema})
        return outputs[len(calls) - 1]

    monkeypatch.setattr(writer, "get_structured_completion", fake)
    return calls


# --------------------------------------------------------- count_sentences

@pytest.mark.parametrize(
    "text, expected",
    [
        ("", 0),
        ("   ", 0),
        ("One sentence only.", 1),
        ("One sentence. Two sentences.", 2),
        ("What a day! Really? Yes. Done.", 4),
        ("The U.S. government acted. Markets fell.", 2),
        ("The U.S. Department acted. Markets fell.", 2),
        ("Dr. Smith said it works. Others agree.", 2),
        ("Acme Inc. Announced a deal. It closed.", 2),
        ("Revenue rose 3.5 percent. Costs fell.", 2),
        ("भारत ने मैच जीता। टीम खुश है।", 2),
        ("पहला वाक्य. दूसरा वाक्य.", 2),
    ],
)
def test_count_sentences(text, expected):
    assert writer.count_sentences(text) == expected


# --------------------------------------------------------- sanitize_key_fact

def test_key_fact_with_source_numbers_is_kept():
    story = {"title": "T", "content": "Funding was $1,200 million in 2026."}
    assert writer.sanitize_key_fact("Funding: 1200 million", story) == (
        "Funding: 1200 million"
    )


def test_key_fact_with_unknown_number_is_dropped():
    story = {"title": "T", "content": "The company raised $50M."}
    assert writer.sanitize_key_fact("It raised $500M", story) is None


def test_key_fact_without_numbers_is_kept():
    story = {"title": "T", "content": "The model beats rivals."}
    assert writer.sanitize_key_fact("Beats rivals", story) == "Beats rivals"


def test_limited_source_story_never_has_key_fact():
    story = {"title": "Raised 50M", "summary": "50M", "content": None}
    assert writer.sanitize_key_fact("Raised 50M", story) is None


def test_blank_key_fact_becomes_none():
    assert writer.sanitize_key_fact("  ", {"content": "x"}) is None
    assert writer.sanitize_key_fact(None, {"content": "x"}) is None


# ---------------------------------------------------------- write_newsletter

def test_writes_subject_and_real_ids_in_input_order(monkeypatch):
    stories = make_stories(2)
    fake_llm(
        monkeypatch,
        [
            WriterOutput(
                subject=" AI weekly ",
                stories=[written(1), written(0)],
            )
        ],
    )

    result = writer.write_newsletter(
        stories, make_analysis(stories), ["AI"], language="en"
    )

    assert result.subject == "AI weekly"
    assert [s.article_id for s in result.stories] == [700, 701]
    assert result.stories[0].headline == "Headline 0"


def test_prompt_has_language_topics_big_picture_and_analysis(monkeypatch):
    stories = make_stories(2)
    stories[0]["content"] = "z" * 5000
    stories[1]["content"] = ""
    calls = fake_llm(
        monkeypatch,
        [WriterOutput(subject="S", stories=[written(0), written(1)])],
    )

    writer.write_newsletter(
        stories, make_analysis(stories), ["AI", "Cricket"], language="hi"
    )

    prompt = calls[0]["prompt"]
    assert "Language: hi" in prompt
    assert "AI, Cricket" in prompt
    assert "Competition is rising." in prompt
    assert "z" * 2000 in prompt and "z" * 2001 not in prompt
    assert '"limited_source": true' in prompt
    assert '"is_speculative": true' in prompt
    assert calls[0]["schema"] is WriterOutput


def test_invented_ids_are_ignored(monkeypatch):
    stories = make_stories(1)
    fake_llm(
        monkeypatch,
        [WriterOutput(subject="S", stories=[written(0), written(99)])],
    )

    result = writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert [s.article_id for s in result.stories] == [700]


def test_wrong_sentence_count_triggers_one_repair(monkeypatch):
    stories = make_stories(1)
    calls = fake_llm(
        monkeypatch,
        [
            WriterOutput(
                subject="S", stories=[written(0, "Only one sentence.")]
            ),
            WriterOutput(subject="S2", stories=[written(0)]),
        ],
    )

    result = writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert len(calls) == 2
    assert "has 1 sentences" in calls[1]["prompt"]
    assert result.subject == "S2"


def test_persistent_sentence_problem_is_returned_not_raised(monkeypatch):
    stories = make_stories(1)
    bad = WriterOutput(
        subject="S", stories=[written(0, "One. Two. Three sentences.")]
    )
    calls = fake_llm(monkeypatch, [bad, bad])

    result = writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert len(calls) == 2
    assert writer.count_sentences(result.stories[0].what_happened) == 3


def test_missing_story_is_repaired_then_raises_if_still_missing(monkeypatch):
    stories = make_stories(2)
    incomplete = WriterOutput(subject="S", stories=[written(0)])
    calls = fake_llm(monkeypatch, [incomplete, incomplete])

    with pytest.raises(ValueError, match="did not cover every story"):
        writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert "Missing stories for IDs [1]" in calls[1]["prompt"]


def test_missing_story_repaired_on_second_attempt(monkeypatch):
    stories = make_stories(2)
    fake_llm(
        monkeypatch,
        [
            WriterOutput(subject="S", stories=[written(0)]),
            WriterOutput(subject="S", stories=[written(0), written(1)]),
        ],
    )

    result = writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert [s.article_id for s in result.stories] == [700, 701]


def test_unsupported_key_fact_is_removed(monkeypatch):
    stories = make_stories(1)
    fake_llm(
        monkeypatch,
        [
            WriterOutput(
                subject="S",
                stories=[
                    written(0, key_fact="Raised 500 million dollars"),
                ],
            )
        ],
    )

    result = writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert result.stories[0].key_fact is None


def test_supported_key_fact_is_kept(monkeypatch):
    stories = make_stories(1)
    fake_llm(
        monkeypatch,
        [
            WriterOutput(
                subject="S",
                stories=[written(0, key_fact="Raised 50 million dollars")],
            )
        ],
    )

    result = writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert result.stories[0].key_fact == "Raised 50 million dollars"


def test_write_rejects_bad_input():
    stories = make_stories(1)

    with pytest.raises(ValueError, match="At least one story"):
        writer.write_newsletter([], make_analysis(stories), ["AI"])

    with pytest.raises(ValueError, match="must have an id"):
        writer.write_newsletter(
            [{"title": "x"}], make_analysis(stories), ["AI"]
        )

    with pytest.raises(ValueError, match="No analyst insight"):
        writer.write_newsletter(
            [{"id": 1, "title": "x"}], make_analysis(stories), ["AI"]
        )


def test_input_stories_are_not_modified(monkeypatch):
    stories = make_stories(1)
    snapshot = [dict(s) for s in stories]
    fake_llm(monkeypatch, [WriterOutput(subject="S", stories=[written(0)])])

    writer.write_newsletter(stories, make_analysis(stories), ["AI"])

    assert stories == snapshot


# ------------------------------------------------------------- revise_story

def test_revise_story_sends_feedback_and_keeps_real_id(monkeypatch):
    story = make_stories(1)[0]
    current = written(700, key_fact="Raised 500 million dollars")
    issue = EditorIssue(
        article_id=700,
        problem="Funding is wrong.",
        correction="Use 50 million dollars.",
    )
    calls = fake_llm(
        monkeypatch,
        [written(0, key_fact="Raised 50 million dollars")],
    )

    result = writer.revise_story(story, current, [issue])

    prompt = calls[0]["prompt"]
    assert "Problem: Funding is wrong." in prompt
    assert "Correction: Use 50 million dollars." in prompt
    assert "Raised 500 million dollars" in prompt
    assert calls[0]["schema"] is WrittenStory
    assert result.article_id == 700
    assert result.key_fact == "Raised 50 million dollars"


def test_revise_story_repairs_sentence_count_once(monkeypatch):
    story = make_stories(1)[0]
    issue = EditorIssue(article_id=700, problem="p", correction="c")
    calls = fake_llm(
        monkeypatch,
        [written(0, "Just one."), written(0)],
    )

    result = writer.revise_story(story, written(700), [issue])

    assert len(calls) == 2
    assert "had 1 sentences" in calls[1]["prompt"]
    assert writer.count_sentences(result.what_happened) == 2


def test_revise_story_drops_unsupported_key_fact(monkeypatch):
    story = make_stories(1)[0]
    issue = EditorIssue(article_id=700, problem="p", correction="c")
    fake_llm(monkeypatch, [written(0, key_fact="Valuation of 10 billion")])

    result = writer.revise_story(story, written(700), [issue])

    assert result.key_fact is None


def test_revise_story_requires_issues():
    with pytest.raises(ValueError, match="editor issue"):
        writer.revise_story(make_stories(1)[0], written(700), [])


# ------------------------------------------------------------ revise_subject

def test_revise_subject_returns_new_subject(monkeypatch):
    issue = EditorIssue(problem="Too dramatic.", correction="Be neutral.")
    calls = fake_llm(monkeypatch, [SubjectRevision(subject=" Calm subject ")])

    result = writer.revise_subject(
        "SHOCKING AI NEWS", [issue], ["Headline A"], language="en"
    )

    assert result == "Calm subject"
    assert "SHOCKING AI NEWS" in calls[0]["prompt"]
    assert "Be neutral." in calls[0]["prompt"]
    assert calls[0]["schema"] is SubjectRevision


def test_revise_subject_requires_issues():
    with pytest.raises(ValueError, match="editor issue"):
        writer.revise_subject("S", [], ["H"])
