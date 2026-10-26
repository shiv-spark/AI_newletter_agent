import re

import pytest

from app.agents.schemas import WrittenStory
from app.services import html_renderer
from app.services.html_renderer import build_render_items, render_newsletter


def story(**overrides):
    values = {
        "headline": "Startup raises funding",
        "what_happened": "A startup raised money. Investors joined.",
        "why_it_matters": "It shows demand.",
        "key_fact": "Raised 50 million dollars",
        "url": "https://example.com/a?x=1&y=2",
        "source_name": "Example News",
    }
    values.update(overrides)
    return values


def render(stories=None, **kwargs):
    kwargs.setdefault("subject", "Weekly AI update")
    kwargs.setdefault("big_picture", "Competition is rising.")
    return render_newsletter(
        stories=stories if stories is not None else [story()], **kwargs
    )


def test_html_contains_all_story_parts():
    html, _ = render()

    for expected in (
        "Weekly AI update",
        "Competition is rising.",
        "Startup raises funding",
        "A startup raised money. Investors joined.",
        "It shows demand.",
        "Raised 50 million dollars",
        "Example News",
        "What Happened",
        "Why It Matters",
        "Key Fact",
        "The Big Picture",
        "Read more",
    ):
        assert expected in html


def test_html_is_responsive_and_has_language():
    html, _ = render(language="en")

    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
    assert "max-width:100%" in html
    assert "@media only screen and (max-width:620px)" in html


def test_html_has_no_external_resources_or_scripts():
    html, _ = render()

    for forbidden in ("<script", "<img", "<link", "<form", "<iframe"):
        assert forbidden not in html.lower()

    # The only URL in the page is the article link.
    assert re.findall(r'(?:src|href)="([^"]+)"', html) == [
        "https://example.com/a?x=1&amp;y=2"
    ]


def test_all_text_is_escaped():
    html, text = render(
        subject="<b>Sub</b>",
        big_picture="<script>alert(1)</script>",
        stories=[
            story(
                headline="<img src=x onerror=alert(1)>",
                what_happened='He said "hi" & left. Done.',
                why_it_matters="<i>x</i>",
                key_fact="<u>1</u>",
                source_name="<Evil>",
            )
        ],
    )

    assert "<script" not in html.lower()
    assert "<img" not in html.lower()
    assert "<b>" not in html and "<i>" not in html and "<u>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&quot;hi&quot; &amp; left" in html
    # The plain text is not HTML, so it keeps the original characters.
    assert "<b>Sub</b>" in text


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "data:text/html,<b>x</b>",
        "ftp://example.com/file",
        "https://",
        "https://exa mple.com",
        "",
        None,
    ],
)
def test_unsafe_urls_get_no_link(bad_url):
    html, text = render(stories=[story(url=bad_url)])

    assert "<a " not in html
    assert "Read more" not in html
    assert "Read more" not in text


def test_key_fact_is_left_out_when_missing():
    for empty in (None, "", "   "):
        html, text = render(stories=[story(key_fact=empty)])
        assert "Key Fact" not in html
        assert "Key Fact" not in text


def test_big_picture_is_left_out_when_missing():
    for empty in (None, "", "  "):
        html, text = render(big_picture=empty)
        assert "The Big Picture" not in html
        assert "THE BIG PICTURE" not in text


def test_big_picture_paragraphs_are_kept_separate():
    html, _ = render(big_picture="First part.\n\nSecond part.")

    assert html.count("First part.") == 1
    assert html.count("Second part.") == 1
    assert "First part.</p>" in html and "Second part.</p>" in html


def test_hindi_labels_and_language_attribute():
    html, text = render(language="hi")

    assert '<html lang="hi">' in html
    assert "क्या हुआ" in html and "क्या हुआ" in text
    assert "What Happened" not in html


def test_unknown_language_falls_back_to_english_labels():
    html, _ = render(language="xx")

    assert "What Happened" in html


def test_language_with_region_uses_base_language_labels():
    html, _ = render(language="hi-IN")

    assert "क्या हुआ" in html


def test_plain_text_version_has_everything_in_order():
    _, text = render(
        stories=[story(), story(headline="Second story", url=None)]
    )

    assert text.startswith("Weekly AI update")
    assert "THE BIG PICTURE\nCompetition is rising." in text
    assert "What Happened: A startup raised money. Investors joined." in text
    assert "Source: Example News" in text
    assert "Key Fact: Raised 50 million dollars" in text
    assert "Read more: https://example.com/a?x=1&y=2" in text
    assert text.index("Startup raises funding") < text.index("Second story")
    assert "\n\n---\n\n" in text


def test_every_story_is_rendered():
    stories = [story(headline=f"Headline {i}") for i in range(5)]

    html, text = render(stories=stories)

    for i in range(5):
        assert f"Headline {i}" in html
        assert f"Headline {i}" in text


def test_missing_source_name_is_skipped_not_shown_as_none():
    html, text = render(stories=[story(source_name=None)])

    assert "None" not in html and "None" not in text
    assert "Source:" not in text


def test_empty_subject_is_rejected():
    for subject in ("", "   ", None):
        with pytest.raises(ValueError, match="Subject"):
            render(subject=subject)


def test_no_stories_is_rejected():
    with pytest.raises(ValueError, match="At least one story"):
        render(stories=[])


def test_build_render_items_adds_url_and_source():
    written = [
        WrittenStory(
            article_id=7,
            headline="H",
            what_happened="One. Two.",
            why_it_matters="M",
            key_fact="F",
        )
    ]
    sources = {7: {"url": "https://example.com/7", "source_name": "Pub"}}

    items = build_render_items(written, sources)

    assert items == [
        {
            "headline": "H",
            "what_happened": "One. Two.",
            "why_it_matters": "M",
            "key_fact": "F",
            "url": "https://example.com/7",
            "source_name": "Pub",
        }
    ]


def test_build_render_items_rejects_unknown_article():
    written = [
        WrittenStory(
            article_id=8,
            headline="H",
            what_happened="One. Two.",
            why_it_matters="M",
        )
    ]

    with pytest.raises(ValueError, match="No source article for story 8"):
        build_render_items(written, {})


def test_render_does_not_modify_its_input():
    stories = [story()]
    snapshot = [dict(s) for s in stories]

    render(stories=stories)

    assert stories == snapshot
    assert html_renderer.LABELS["en"]["what_happened"] == "What Happened"
