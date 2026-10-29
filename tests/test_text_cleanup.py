import pytest

from app.agents.schemas import AnalystOutput, StoryInsight, WrittenStory
from app.agents.text_cleanup import fix_spacing


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Reported by Telegraph India.No further details.",
         "Reported by Telegraph India. No further details."),
        ("Really?Yes it is.", "Really? Yes it is."),
        ("It fell!Markets reacted.", "It fell! Markets reacted."),
    ],
)
def test_missing_space_after_sentence_end_is_added(text, expected):
    assert fix_spacing(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "The U.S.Government acted.",      # initials
        "Revenue rose 3.5 percent.",      # decimal number
        "It runs on Node.js today.",      # lowercase after the dot
        "Dr.Smith said so.",              # one-letter abbreviation start
        "Visit Bloomberg.com for more.",  # domain name
        "Already fine. Nothing to do.",   # correct text
        "",
    ],
)
def test_legitimate_text_is_left_alone(text):
    assert fix_spacing(text) == text


def test_written_story_text_is_repaired():
    story = WrittenStory(
        article_id=1,
        headline="H",
        what_happened="It cut access, says Telegraph India.No more is known.",
        why_it_matters="It matters.",
    )

    assert "India. No more" in story.what_happened


def test_big_picture_is_repaired():
    output = AnalystOutput(
        big_picture="Costs are rising.Investors are wary.",
        stories=[
            StoryInsight(
                article_id=1, what_happened="a", why_it_matters="b", impact="c"
            )
        ],
    )

    assert output.big_picture == "Costs are rising. Investors are wary."