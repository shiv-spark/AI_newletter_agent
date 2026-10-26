"""Render an approved newsletter as a responsive HTML email.

Returns an HTML version and a plain-text version of the same content
(the plain text is the email's fallback and is stored in `body`).

Email-client rules followed here:
- table layout with inline CSS (many clients ignore <style> blocks),
  plus one small media query for phones
- single 600px column that shrinks on small screens
- no images, scripts, forms or external resources
- every piece of text from the AI or from articles is HTML-escaped, and
  links are only created for http/https URLs
"""
import html
from urllib.parse import urlsplit

from app.agents.schemas import WrittenStory

LABELS = {
    "en": {
        "big_picture": "The Big Picture",
        "what_happened": "What Happened",
        "why_it_matters": "Why It Matters",
        "key_fact": "Key Fact",
        "source": "Source",
        "read_more": "Read more",
    },
    "hi": {
        "big_picture": "बड़ी तस्वीर",
        "what_happened": "क्या हुआ",
        "why_it_matters": "यह क्यों मायने रखता है",
        "key_fact": "मुख्य तथ्य",
        "source": "स्रोत",
        "read_more": "और पढ़ें",
    },
}

FONT = "Arial, Helvetica, sans-serif"


def build_render_items(
    written_stories: list[WrittenStory],
    sources: dict[int, dict],
) -> list[dict]:
    """Combine the Writer's text with each article's URL and publisher."""
    items = []

    for story in written_stories:
        source = sources.get(story.article_id)

        if source is None:
            raise ValueError(
                f"No source article for story {story.article_id}."
            )

        items.append(
            {
                "headline": story.headline,
                "what_happened": story.what_happened,
                "why_it_matters": story.why_it_matters,
                "key_fact": story.key_fact,
                "url": source.get("url"),
                "source_name": source.get("source_name"),
            }
        )

    return items


def _labels(language: str) -> dict:
    return LABELS.get((language or "en").split("-")[0].lower(), LABELS["en"])


def _safe_url(url: str | None) -> str | None:
    """Return the URL only if it is a plain http/https link."""
    if not url or not url.strip():
        return None

    url = url.strip()

    try:
        parts = urlsplit(url)
    except ValueError:
        return None

    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None

    if any(char.isspace() for char in url):
        return None

    return url


def _paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in (text or "").split("\n\n")]
    return [part for part in parts if part]


def _esc(text: str | None) -> str:
    return html.escape(text or "", quote=True)


def _section(label: str, text: str) -> str:
    return (
        '<p style="margin:14px 0 2px 0;font-family:%s;font-size:12px;'
        'font-weight:bold;letter-spacing:0.5px;text-transform:uppercase;'
        'color:#6b7280;">%s</p>'
        '<p style="margin:0;font-family:%s;font-size:16px;line-height:1.5;'
        'color:#111827;">%s</p>'
    ) % (FONT, _esc(label), FONT, _esc(text))


def render_newsletter(
    subject: str,
    big_picture: str | None,
    stories: list[dict],
    language: str = "en",
) -> tuple[str, str]:
    """Return (html, plain_text) for an approved newsletter.

    `stories` are dicts from build_render_items(): headline,
    what_happened, why_it_matters, key_fact, url, source_name.
    """
    subject = (subject or "").strip()

    if not subject:
        raise ValueError("Subject cannot be empty.")

    if not stories:
        raise ValueError("At least one story is required.")

    labels = _labels(language)
    big_picture = (big_picture or "").strip()

    # ------------------------------------------------------------ HTML
    blocks = []

    blocks.append(
        '<tr><td class="pad" style="padding:28px 32px 8px 32px;">'
        '<h1 style="margin:0;font-family:%s;font-size:24px;'
        'line-height:1.3;color:#111827;">%s</h1></td></tr>'
        % (FONT, _esc(subject))
    )

    if big_picture:
        paragraphs = "".join(
            '<p style="margin:8px 0 0 0;font-family:%s;font-size:16px;'
            'line-height:1.5;color:#111827;">%s</p>' % (FONT, _esc(p))
            for p in _paragraphs(big_picture)
        )
        blocks.append(
            '<tr><td class="pad" style="padding:16px 32px;">'
            '<div style="background:#eef2ff;border-left:4px solid #4f46e5;'
            'padding:14px 16px;">'
            '<p style="margin:0;font-family:%s;font-size:12px;'
            'font-weight:bold;letter-spacing:0.5px;'
            'text-transform:uppercase;color:#4338ca;">%s</p>%s'
            "</div></td></tr>" % (FONT, _esc(labels["big_picture"]), paragraphs)
        )

    for story in stories:
        parts = [
            '<h2 style="margin:0 0 4px 0;font-family:%s;font-size:20px;'
            'line-height:1.3;color:#111827;">%s</h2>'
            % (FONT, _esc(story.get("headline")))
        ]

        if (story.get("source_name") or "").strip():
            parts.append(
                '<p style="margin:0;font-family:%s;font-size:13px;'
                'color:#6b7280;">%s: %s</p>'
                % (
                    FONT,
                    _esc(labels["source"]),
                    _esc(story["source_name"].strip()),
                )
            )

        parts.append(
            _section(labels["what_happened"], story.get("what_happened"))
        )
        parts.append(
            _section(labels["why_it_matters"], story.get("why_it_matters"))
        )

        if (story.get("key_fact") or "").strip():
            parts.append(
                _section(labels["key_fact"], story["key_fact"].strip())
            )

        url = _safe_url(story.get("url"))

        if url:
            parts.append(
                '<p style="margin:14px 0 0 0;font-family:%s;'
                'font-size:15px;"><a href="%s" style="color:#4f46e5;">%s'
                "</a></p>" % (FONT, _esc(url), _esc(labels["read_more"]))
            )

        blocks.append(
            '<tr><td class="pad" style="padding:20px 32px;'
            'border-top:1px solid #e5e7eb;">%s</td></tr>' % "".join(parts)
        )

    html_body = (
        "<!DOCTYPE html>\n"
        '<html lang="%s"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, '
        'initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        "<title>%s</title>"
        "<style>@media only screen and (max-width:620px){"
        ".container{width:100%%!important;}"
        ".pad{padding-left:16px!important;padding-right:16px!important;}"
        "}</style></head>"
        '<body style="margin:0;padding:0;background:#f3f4f6;">'
        '<table role="presentation" width="100%%" cellpadding="0" '
        'cellspacing="0" style="background:#f3f4f6;"><tr>'
        '<td align="center" style="padding:24px 12px;">'
        '<table role="presentation" class="container" width="600" '
        'cellpadding="0" cellspacing="0" style="width:600px;'
        'max-width:100%%;background:#ffffff;border-radius:8px;">'
        "%s</table></td></tr></table></body></html>"
        % (
            _esc((language or "en").strip()),
            _esc(subject),
            "".join(blocks),
        )
    )

    # ------------------------------------------------------ plain text
    text_sections = [subject]

    if big_picture:
        text_sections.append(f"{labels['big_picture'].upper()}\n{big_picture}")

    for story in stories:
        lines = [(story.get("headline") or "").strip()]

        if (story.get("source_name") or "").strip():
            lines.append(f"{labels['source']}: {story['source_name'].strip()}")

        lines.append(
            f"{labels['what_happened']}: {(story.get('what_happened') or '').strip()}"
        )
        lines.append(
            f"{labels['why_it_matters']}: {(story.get('why_it_matters') or '').strip()}"
        )

        if (story.get("key_fact") or "").strip():
            lines.append(f"{labels['key_fact']}: {story['key_fact'].strip()}")

        url = _safe_url(story.get("url"))

        if url:
            lines.append(f"{labels['read_more']}: {url}")

        text_sections.append("\n".join(lines))

    plain_text = "\n\n---\n\n".join(text_sections)

    return html_body, plain_text
