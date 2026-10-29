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

Email clients cannot run animation, so the email only gets the *look* of
the live web view (dark green gradient, mint accents). The animated
version is the /api/issues/{id}/live page.
"""
import html
import logging
from urllib.parse import urlsplit

from app.agents.schemas import WrittenStory
from app.config import settings
from app.services.branding import brand_name

logger = logging.getLogger(__name__)

LABELS = {
    "en": {
        "big_picture": "The Big Picture",
        "what_happened": "What Happened",
        "why_it_matters": "Why It Matters",
        "key_fact": "Key Fact",
        "source": "Source",
        "read_more": "Read more",
        "newsletter": "AI Newsletter",
        "sent_by": "Sent by {brand}",
    },
    "hi": {
        "big_picture": "बड़ी तस्वीर",
        "what_happened": "क्या हुआ",
        "why_it_matters": "यह क्यों मायने रखता है",
        "key_fact": "मुख्य तथ्य",
        "source": "स्रोत",
        "read_more": "और पढ़ें",
        "newsletter": "एआई न्यूज़लेटर",
        "sent_by": "{brand} की ओर से",
    },
}

FONT = "Arial, Helvetica, sans-serif"

# Colours for each theme. Solid colours only (plus one optional gradient
# on top of a solid fallback), because many email clients ignore the rest.
THEMES = {
    "light": {
        "page": "#f3f4f6",
        "page_image": None,
        "card": "#ffffff",
        "card_border": "none",
        "title": "#111827",
        "text": "#111827",
        "muted": "#6b7280",
        "rule": "#e5e7eb",
        "accent": "#4f46e5",
        "box_bg": "#eef2ff",
        "box_edge": "#4f46e5",
        "box_label": "#4338ca",
        "scheme": "light",
    },
    "forest": {
        "page": "#083a2d",
        "page_image": (
            "linear-gradient(158deg,#0b4634 0%,#083a2d 44%,#03150f 100%)"
        ),
        "card": "#0c4534",
        "card_border": "1px solid #1d6b52",
        "title": "#f4fbf7",
        "text": "#eef7f2",
        "muted": "#a9c7b9",
        "rule": "#1d6b52",
        "accent": "#5ff0b0",
        "box_bg": "#0a3a2c",
        "box_edge": "#5ff0b0",
        "box_label": "#5ff0b0",
        "scheme": "dark",
    },
}
DEFAULT_THEME = "forest"
THEME_META_NAME = "newsletter-theme"


def _palette(theme: str | None) -> tuple[str, dict]:
    """The theme name and its colours; unknown names fall back safely."""
    name = (theme or settings.newsletter_theme or DEFAULT_THEME).strip().lower()

    if name not in THEMES:
        logger.warning(
            "Unknown newsletter theme %r, using %r.", name, DEFAULT_THEME
        )
        name = DEFAULT_THEME

    return name, THEMES[name]


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


def _section(label: str, text: str, colors: dict) -> str:
    return (
        '<p style="margin:14px 0 2px 0;font-family:%s;font-size:12px;'
        'font-weight:bold;letter-spacing:0.5px;text-transform:uppercase;'
        'color:%s;">%s</p>'
        '<p style="margin:0;font-family:%s;font-size:16px;line-height:1.5;'
        'color:%s;">%s</p>'
    ) % (FONT, colors["muted"], _esc(label), FONT, colors["text"], _esc(text))


def render_newsletter(
    subject: str,
    big_picture: str | None,
    stories: list[dict],
    language: str = "en",
    theme: str | None = None,
    brand: str | None = None,
    unsubscribe_url: str | None = None,
) -> tuple[str, str]:
    """Return (html, plain_text) for an approved newsletter.

    `stories` are dicts from build_render_items(): headline,
    what_happened, why_it_matters, key_fact, url, source_name.
    `theme` is "forest" or "light"; None uses NEWSLETTER_THEME.
    `brand` is shown in the header and footer; None uses NEWSLETTER_BRAND.
    `unsubscribe_url` adds an unsubscribe link to the footer if present.
    """
    subject = (subject or "").strip()

    if not subject:
        raise ValueError("Subject cannot be empty.")

    if not stories:
        raise ValueError("At least one story is required.")

    labels = _labels(language)
    big_picture = (big_picture or "").strip()
    theme_name, c = _palette(theme)
    brand = (brand_name() if brand is None else brand).strip()
    brand_line = (
        f"{brand} · {labels['newsletter']}" if brand else labels["newsletter"]
    )
    sent_by = labels["sent_by"].format(brand=brand) if brand else ""

    # ------------------------------------------------------------ HTML
    blocks = []

    blocks.append(
        '<tr><td class="pad" style="padding:26px 32px 8px 32px;">'
        '<p style="margin:0 0 8px 0;font-family:%s;font-size:12px;'
        'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
        'color:%s;">%s</p>'
        '<h1 style="margin:0;font-family:%s;font-size:20px;'
        'line-height:1.3;color:%s;">%s</h1></td></tr>'
        % (FONT, c["accent"], _esc(brand_line), FONT, c["title"], _esc(subject))
    )

    if big_picture:
        paragraphs = "".join(
            '<p style="margin:8px 0 0 0;font-family:%s;font-size:16px;'
            'line-height:1.5;color:%s;">%s</p>' % (FONT, c["text"], _esc(p))
            for p in _paragraphs(big_picture)
        )
        blocks.append(
            '<tr><td class="pad" style="padding:16px 32px;">'
            '<div style="background:%s;border-left:4px solid %s;'
            'padding:14px 16px;">'
            '<p style="margin:0;font-family:%s;font-size:12px;'
            'font-weight:bold;letter-spacing:0.5px;'
            'text-transform:uppercase;color:%s;">%s</p>%s'
            "</div></td></tr>"
            % (
                c["box_bg"],
                c["box_edge"],
                FONT,
                c["box_label"],
                _esc(labels["big_picture"]),
                paragraphs,
            )
        )

    for story in stories:
        parts = [
            '<h2 style="margin:0 0 4px 0;font-family:%s;font-size:17px;'
            'line-height:1.3;color:%s;">%s</h2>'
            % (FONT, c["title"], _esc(story.get("headline")))
        ]

        if (story.get("source_name") or "").strip():
            parts.append(
                '<p style="margin:0;font-family:%s;font-size:13px;'
                'color:%s;">%s: %s</p>'
                % (
                    FONT,
                    c["muted"],
                    _esc(labels["source"]),
                    _esc(story["source_name"].strip()),
                )
            )

        parts.append(
            _section(labels["what_happened"], story.get("what_happened"), c)
        )
        parts.append(
            _section(labels["why_it_matters"], story.get("why_it_matters"), c)
        )

        if (story.get("key_fact") or "").strip():
            parts.append(
                _section(labels["key_fact"], story["key_fact"].strip(), c)
            )

        url = _safe_url(story.get("url"))

        if url:
            parts.append(
                '<p style="margin:14px 0 0 0;font-family:%s;'
                'font-size:15px;"><a href="%s" style="color:%s;">%s'
                "</a></p>"
                % (FONT, _esc(url), c["accent"], _esc(labels["read_more"]))
            )

        blocks.append(
            '<tr><td class="pad" style="padding:20px 32px;'
            'border-top:1px solid %s;">%s</td></tr>'
            % (c["rule"], "".join(parts))
        )

    footer_items = []
    if sent_by:
        footer_items.append(_esc(sent_by))
    if unsubscribe_url:
        footer_items.append(
            '<a href="%s" style="color:%s;text-decoration:underline;">Unsubscribe</a>'
            % (_esc(unsubscribe_url), c["muted"])
        )

    if footer_items:
        blocks.append(
            '<tr><td class="pad" style="padding:16px 32px 22px 32px;'
            'border-top:1px solid %s;">'
            '<p style="margin:0;font-family:%s;font-size:12px;'
            'text-align:center;color:%s;">%s</p></td></tr>'
            % (c["rule"], FONT, c["muted"], " · ".join(footer_items))
        )

    # Solid colour first, gradient on top: clients without gradient
    # support still show the solid colour.
    page_style = "background:%s;" % c["page"]

    if c["page_image"]:
        page_style += "background-image:%s;" % c["page_image"]

    html_body = (
        "<!DOCTYPE html>\n"
        '<html lang="%s"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, '
        'initial-scale=1">'
        '<meta name="color-scheme" content="%s">'
        '<meta name="supported-color-schemes" content="%s">'
        '<meta name="%s" content="%s">'
        "<title>%s</title>"
        "<style>@media only screen and (max-width:620px){"
        ".container{width:100%%!important;}"
        ".pad{padding-left:16px!important;padding-right:16px!important;}"
        "}</style></head>"
        '<body bgcolor="%s" style="margin:0;padding:0;%s">'
        '<table role="presentation" width="100%%" cellpadding="0" '
        'cellspacing="0" bgcolor="%s" style="%s"><tr>'
        '<td align="center" style="padding:24px 12px;">'
        '<table role="presentation" class="container" width="600" '
        'cellpadding="0" cellspacing="0" bgcolor="%s" style="width:600px;'
        'max-width:100%%;background:%s;border:%s;border-radius:8px;">'
        "%s</table></td></tr></table></body></html>"
        % (
            _esc((language or "en").strip()),
            c["scheme"],
            c["scheme"],
            THEME_META_NAME,
            theme_name,
            _esc(subject),
            c["page"],
            page_style,
            c["page"],
            page_style,
            c["card"],
            c["card"],
            c["card_border"],
            "".join(blocks),
        )
    )

    # ------------------------------------------------------ plain text
    text_sections = [f"{subject}\n{brand_line}"]

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

    footer_text = []
    if sent_by:
        footer_text.append(sent_by)
    if unsubscribe_url:
        footer_text.append(f"Unsubscribe: {unsubscribe_url}")

    if footer_text:
        text_sections.append(" · ".join(footer_text))

    plain_text = "\n\n---\n\n".join(text_sections)

    return html_body, plain_text
