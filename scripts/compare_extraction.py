
"""Compare article extraction on real news URLs.

Runs several extractors on the same URLs and writes a CSV plus a Markdown
report, so the results can be scored by hand.

Extractors
    current          the existing pipeline: research.extract_article_content()
    traf_precision   Trafilatura, favor_precision=True  (what the project uses)
    traf_balanced    Trafilatura, default settings
    traf_recall      Trafilatura, favor_recall=True
    crawl4ai_raw     Crawl4AI raw markdown      (only with --crawl4ai)
    crawl4ai_fit     Crawl4AI pruned markdown   (only with --crawl4ai)
    traf_on_c4ai_html  Trafilatura run on the HTML that Crawl4AI's browser
                     received (only with --crawl4ai). Use it when a site
                     blocks plain downloads (HTTP 403): it compares the two
                     extraction methods on the same page.

The three Trafilatura variants share one download that uses a browser-like
User-Agent and passes raw bytes (not response.text), so differences between
them and "current" show what those two choices change.

Usage (run from the project root)
    python scripts/compare_extraction.py URL1 URL2 URL3
    python scripts/compare_extraction.py --file urls.txt
    python scripts/compare_extraction.py --from-db 8
    python scripts/compare_extraction.py --file urls.txt --crawl4ai
    python scripts/compare_extraction.py --scores extraction_results/extraction_results.csv

Crawl4AI's Markdown is converted to plain text first (links, images and
symbols removed), so its lengths can be compared with Trafilatura's.

Nothing is written to the database.
"""
import argparse
import asyncio
import csv
import difflib
import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Hide Crawl4AI's promotional banners in the console output.
os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402
import trafilatura  # noqa: E402

from app.agents.research import (  # noqa: E402
    extract_article_content,
    resolve_article_url,
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MIN_LENGTH = 300  # same rule as the current pipeline
FETCH_TIMEOUT = 20

# Phrases that usually mean page furniture leaked into the article text.
JUNK_PHRASES = [
    "subscribe", "sign up", "newsletter", "cookie", "advertisement",
    "also read", "read more", "follow us", "click here", "all rights reserved",
    "download the app", "share this", "related articles", "trending",
    "terms of use", "privacy policy",
]

TRAF_VARIANTS = {
    "traf_precision": {"favor_precision": True},
    "traf_balanced": {},
    "traf_recall": {"favor_recall": True},
}

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\u0964])\s+|\n+")
_TOKEN = re.compile(r"[^\s.,;:!?\"'()\[\]{}\u0964<>|*#_`-]+")
COVERED_SHARE = 0.8  # a sentence counts as "found" if 80% of its words are


def strip_markdown(text):
    """Crawl4AI returns Markdown. Remove the Markdown syntax so its text can
    be compared fairly with Trafilatura's plain text (link URLs and symbols
    would otherwise inflate its length)."""
    text = _MD_IMAGE.sub("", text or "")
    text = _MD_LINK.sub(r"\1", text)
    text = _BARE_URL.sub("", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*`]+", "", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def tokens(text):
    return _TOKEN.findall((text or "").lower())


def sentences(text):
    """(original sentence, words) pairs for sentences of 5+ words."""
    found = []
    for part in _SENTENCE_SPLIT.split(text or ""):
        part = part.strip()
        words = tokens(part)
        if len(words) >= 5:
            found.append((part, words))
    return found


def missing_sentences(source_text, other_text):
    """Sentences of source_text that mostly do not appear in other_text."""
    other_words = set(tokens(other_text))
    missing = []
    for original, words in sentences(source_text):
        share = sum(w in other_words for w in words) / len(words)
        if share < COVERED_SHARE:
            missing.append(original)
    return missing


def coverage(source_text, other_text):
    """Share (0-1) of source_text's sentences that are found in other_text."""
    total = len(sentences(source_text))
    if not total:
        return None
    return 1 - len(missing_sentences(source_text, other_text)) / total


EXTRACTOR_ORDER = [
    "current", "traf_precision", "traf_balanced", "traf_recall",
    "crawl4ai_raw", "crawl4ai_fit", "traf_on_c4ai_html",
]


# --------------------------------------------------------------------------
# One result row
# --------------------------------------------------------------------------

def make_result(url, extractor, status, text="", seconds=0.0, meta=None,
                final_url=None):
    text = text or ""
    lowered = text.lower()
    junk = {p: lowered.count(p) for p in JUNK_PHRASES if p in lowered}
    meta = meta or {}
    return {
        "_text": text,  # kept in memory for the comparison, not in the CSV
        "url": url,
        "final_url": final_url or url,
        "extractor": extractor,
        "status": status,
        "seconds": round(seconds, 2),
        "chars": len(text),
        "words": len(text.split()),
        "paragraphs": len([b for b in text.splitlines() if b.strip()]),
        "junk_total": sum(junk.values()),
        "junk_phrases": ", ".join(f"{k}x{v}" for k, v in junk.items()),
        "title": meta.get("title") or "",
        "author": meta.get("author") or "",
        "date": meta.get("date") or "",
        "sitename": meta.get("sitename") or "",
        "title_similarity": "",
        "date_check": "",
        "head": " ".join(text[:300].split()),
        "tail": " ".join(text[-300:].split()) if text else "",
        "completeness_1_5": "",
        "noise_1_5": "",
        "metadata_1_5": "",
    }


def length_status(text):
    return "success" if len(text) >= MIN_LENGTH else "insufficient_content"


# --------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------

def run_current(url):
    start = time.perf_counter()
    out = extract_article_content(url)
    seconds = time.perf_counter() - start
    return make_result(
        url, "current", out["status"], out["content"], seconds,
        final_url=out["final_url"],
    )


def fetch_html(url):
    """Download once with a browser-like User-Agent. Returns raw bytes."""
    resolved = resolve_article_url(url)
    start = time.perf_counter()
    response = requests.get(
        resolved,
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": BROWSER_USER_AGENT},
        allow_redirects=True,
    )
    seconds = time.perf_counter() - start
    return response, seconds


def trafilatura_on_html(url, name, html, final_url, options):
    """Run Trafilatura on HTML we already have. html may be bytes or text."""
    start = time.perf_counter()
    try:
        raw = trafilatura.extract(
            html,  # bytes are best: Trafilatura detects the charset itself
            url=final_url,
            include_comments=False,
            include_tables=False,
            output_format="json",
            with_metadata=True,
            **options,
        )
    except Exception as exc:  # keep going on one bad page
        return make_result(url, name, f"extraction_failed: {type(exc).__name__}",
                           final_url=final_url)
    seconds = time.perf_counter() - start

    if not raw:
        return make_result(url, name, "no_content", seconds=seconds,
                           final_url=final_url)

    data = json.loads(raw)
    text = (data.get("text") or data.get("raw_text") or "").strip()
    # Different Trafilatura versions name the site differently.
    data["sitename"] = (
        data.get("sitename") or data.get("source-hostname") or data.get("hostname")
    )
    return make_result(url, name, length_status(text), text, seconds, data,
                       final_url=final_url)


def run_trafilatura_variants(url):
    """All Trafilatura variants on one shared download."""
    try:
        response, fetch_seconds = fetch_html(url)
    except requests.RequestException as exc:
        status = f"fetch_failed: {type(exc).__name__}"
        return [make_result(url, name, status) for name in TRAF_VARIANTS]

    if response.status_code >= 400:
        status = f"http_{response.status_code}"
        return [
            make_result(url, name, status, final_url=response.url)
            for name in TRAF_VARIANTS
        ]

    return [
        trafilatura_on_html(url, name, response.content, response.url, options)
        for name, options in TRAF_VARIANTS.items()
    ]


async def _crawl4ai_all(urls, no_sandbox=False, wait=1.0):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    try:  # newer versions renamed the pruning filter
        from crawl4ai.content_filter_strategy import (
            PruningContentFilterLXML as PruningFilter,
        )
    except ImportError:
        from crawl4ai.content_filter_strategy import (
            PruningContentFilter as PruningFilter,
        )

    config = CrawlerRunConfig(
        markdown_generator=DefaultMarkdownGenerator(content_filter=PruningFilter()),
        # Give JavaScript time to build the page before the text is taken.
        delay_before_return_html=wait,
        verbose=False,
    )
    browser = BrowserConfig(
        verbose=False,
        extra_args=["--no-sandbox"] if no_sandbox else [],
    )
    output = {}

    async with AsyncWebCrawler(config=browser) as crawler:
        for url in urls:
            start = time.perf_counter()
            try:
                result = await crawler.arun(url=resolve_article_url(url),
                                            config=config)
            except Exception as exc:
                status = f"crawl_failed: {type(exc).__name__}"
                output[url] = [
                    make_result(url, "crawl4ai_raw", status),
                    make_result(url, "crawl4ai_fit", status),
                ]
                continue
            seconds = time.perf_counter() - start

            markdown = result.markdown
            raw_text = strip_markdown(
                getattr(markdown, "raw_markdown", None) or str(markdown or "")
            )
            fit_text = strip_markdown(getattr(markdown, "fit_markdown", None) or "")

            # success=False can still come with usable text, so keep it.
            failed = not getattr(result, "success", True)
            error = (getattr(result, "error_message", "") or "")[:80]

            page = getattr(result, "metadata", None) or {}
            meta = {
                "title": page.get("title"),
                "author": page.get("author"),
                "date": page.get("article:published_time")
                or page.get("published_time"),
                "sitename": page.get("og:site_name"),
            }

            def status_for(text):
                if not text:
                    return f"crawl_failed: {error}" if failed else "no_content"
                return length_status(text)

            rows = [
                make_result(url, "crawl4ai_raw", status_for(raw_text),
                            raw_text, seconds, meta),
                make_result(url, "crawl4ai_fit", status_for(fit_text),
                            fit_text, seconds, meta),
            ]

            # Trafilatura on the HTML the browser saw. This separates "could
            # not download the page" from "could not extract the article".
            browser_html = getattr(result, "html", "") or ""
            if browser_html:
                rows.append(trafilatura_on_html(
                    url, "traf_on_c4ai_html", browser_html, url, {}
                ))
            output[url] = rows
    return output


def run_crawl4ai(urls, no_sandbox=False, wait=1.0):
    try:
        return asyncio.run(_crawl4ai_all(urls, no_sandbox, wait))
    except ImportError:
        print(
            "\nCrawl4AI is not installed, so it was skipped.\n"
            "Install it in a separate environment with:\n"
            "    pip install crawl4ai\n    crawl4ai-setup\n"
        )
        return {}


# --------------------------------------------------------------------------
# Metadata check against what the RSS feed said (only with --from-db)
# --------------------------------------------------------------------------

def _clean_title(title):
    title = (title or "").strip()
    if " - " in title:  # Google News adds " - Source name"
        title = title.rsplit(" - ", 1)[0]
    return " ".join(title.lower().split())


def add_metadata_checks(rows, expected):
    expected_title = _clean_title(expected.get("title"))
    expected_date = expected.get("published_at")

    for row in rows:
        if expected_title and row["title"]:
            ratio = difflib.SequenceMatcher(
                None, expected_title, _clean_title(row["title"])
            ).ratio()
            row["title_similarity"] = round(ratio, 2)

        if not expected_date:
            continue
        if not row["date"]:
            row["date_check"] = "missing"
            continue
        try:
            found = datetime.fromisoformat(row["date"][:10]).replace(
                tzinfo=timezone.utc
            )
            close = abs(found - expected_date.replace(hour=0, minute=0,
                        second=0, microsecond=0)) <= timedelta(days=1)
            row["date_check"] = "ok" if close else "differs"
        except ValueError:
            row["date_check"] = "unreadable"


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------

def urls_from_db(count):
    """Recent articles from the database, one per source where possible."""
    from sqlalchemy import select

    from app.database.db import SessionLocal
    from app.database.models import Article

    with SessionLocal() as session:
        articles = session.scalars(
            select(Article).order_by(Article.created_at.desc()).limit(200)
        ).all()

    chosen, seen_sources = [], set()
    for article in articles:
        if article.source_name not in seen_sources:
            seen_sources.add(article.source_name)
            chosen.append(article)
    for article in articles:
        if len(chosen) >= count:
            break
        if article not in chosen:
            chosen.append(article)

    expected = {}
    for article in chosen[:count]:
        expected[article.url] = {
            "title": article.title,
            "published_at": article.published_at,
            "source_name": article.source_name,
        }
    return expected


def read_url_file(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

CSV_COLUMNS = [
    "url", "final_url", "extractor", "status", "seconds", "chars", "words",
    "paragraphs", "junk_total", "junk_phrases", "title", "author", "date",
    "sitename", "title_similarity", "date_check", "head", "tail",
    "completeness_1_5", "noise_1_5", "metadata_1_5",
]


def write_csv(rows, path):
    # utf-8-sig so Excel on Windows shows Hindi text correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    """Per-extractor totals."""
    summary = {}
    for row in rows:
        item = summary.setdefault(row["extractor"], {
            "pages": 0, "success": 0, "chars": 0, "junk": 0, "seconds": 0.0,
        })
        item["pages"] += 1
        item["success"] += row["status"] == "success"
        item["chars"] += row["chars"]
        item["junk"] += row["junk_total"]
        item["seconds"] += row["seconds"]
    return summary


def _short(text, limit=150):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def comparison_lines(page_rows, names):
    """Which extractor's sentences are found in which other extractor."""
    usable = [n for n in names if page_rows.get(n) and page_rows[n]["_text"]]
    lines = []
    if len(usable) < 2:
        return lines

    lines += [
        "", "**Agreement**: share of the ROW extractor's sentences that also "
        "appear in the COLUMN extractor (100% = nothing missing).", "",
        "| row \\ column | " + " | ".join(usable) + " |",
        "|---|" + "---|" * len(usable),
    ]
    for a in usable:
        cells = []
        for b in usable:
            if a == b:
                cells.append("-")
                continue
            value = coverage(page_rows[a]["_text"], page_rows[b]["_text"])
            cells.append("n/a" if value is None else f"{value:.0%}")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")

    def only_in(a, b, label):
        if a not in usable or b not in usable:
            return
        extra = missing_sentences(page_rows[a]["_text"], page_rows[b]["_text"])
        if not extra:
            lines.append(f"- {label}: nothing")
            return
        lines.append(f"- {label} ({len(extra)} sentences), for example:")
        lines.extend(f"  - {_short(x)}" for x in extra[:3])

    lines += ["", "**What each one has that the other lacks:**", ""]
    only_in("crawl4ai_fit", "traf_balanced", "Only in crawl4ai_fit, not in traf_balanced")
    only_in("traf_balanced", "crawl4ai_fit", "Only in traf_balanced, not in crawl4ai_fit")
    only_in("crawl4ai_raw", "traf_balanced", "Only in crawl4ai_raw, not in traf_balanced")
    only_in("crawl4ai_fit", "traf_on_c4ai_html",
            "Only in crawl4ai_fit, not in traf_on_c4ai_html")
    only_in("traf_on_c4ai_html", "crawl4ai_fit",
            "Only in traf_on_c4ai_html, not in crawl4ai_fit")
    only_in("traf_balanced", "current", "Only in traf_balanced, not in current")
    return lines


def write_report(rows, expected, path):
    names = [n for n in EXTRACTOR_ORDER if any(r["extractor"] == n for r in rows)]
    summary = summarize(rows)
    urls = list(dict.fromkeys(r["url"] for r in rows))

    lines = [
        "# Article extraction comparison",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
        f"{len(urls)} URLs, extractors: {', '.join(names)}.",
        "",
        "Seconds are not directly comparable: `current` and Crawl4AI include "
        "their own page download, the Trafilatura variants only the extraction.",
        "",
        "## Totals",
        "",
        "| Extractor | Success | Avg chars | Avg junk phrases | Avg seconds |",
        "|---|---|---|---|---|",
    ]
    for name in names:
        item = summary[name]
        pages = item["pages"] or 1
        lines.append(
            f"| {name} | {item['success']}/{item['pages']} | "
            f"{item['chars'] // pages} | {item['junk'] / pages:.1f} | "
            f"{item['seconds'] / pages:.2f} |"
        )

    for number, url in enumerate(urls, start=1):
        page_rows = {r["extractor"]: r for r in rows if r["url"] == url}
        lines += ["", f"## {number}. {url}", ""]

        info = expected.get(url)
        if info:
            published = info["published_at"]
            lines += [
                f"RSS says: title **{info['title']}**, source "
                f"**{info['source_name']}**, published "
                f"**{published.date() if published else 'no date'}**.",
                "",
            ]

        lines += [
            "| Extractor | Status | Chars | Paragraphs | Junk | Title match "
            "| Date | Author | Sitename |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name in names:
            r = page_rows.get(name)
            if not r:
                continue
            lines.append(
                f"| {name} | {r['status']} | {r['chars']} | {r['paragraphs']} "
                f"| {r['junk_total']} | {r['title_similarity']} "
                f"| {r['date'] or r['date_check']} | {r['author']} "
                f"| {r['sitename']} |"
            )

        for name in names:
            r = page_rows.get(name)
            if not r or not r["head"]:
                continue
            lines += [
                "", f"**{name}** start: {r['head']}",
                "", f"**{name}** end: {r['tail']}",
            ]
            if r["junk_phrases"]:
                lines += ["", f"**{name}** junk found: {r['junk_phrases']}"]

        lines += comparison_lines(page_rows, names)

    lines += [
        "", "---", "",
        "To score: open `extraction_results.csv` in Excel and fill "
        "`completeness_1_5`, `noise_1_5` and `metadata_1_5` for each row "
        "(1 = bad, 5 = excellent). Then run:", "",
        "    python scripts/compare_extraction.py --scores "
        "extraction_results/extraction_results.csv",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


EXTRACTOR_LABELS = {
    "current": "Current pipeline (project today)",
    "traf_precision": "Trafilatura (favor_precision, project setting)",
    "traf_balanced": "Trafilatura (default)",
    "traf_recall": "Trafilatura (favor_recall)",
    "crawl4ai_raw": "Crawl4AI (raw)",
    "crawl4ai_fit": "Crawl4AI (fit / pruned)",
    "traf_on_c4ai_html": "Trafilatura on Crawl4AI's HTML",
}

SIDE_BY_SIDE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Extraction side by side</title>
<style>
:root{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#d9d9de;--card:#f6f6f8;--mark:#fff3a3;--bad:#b3261e;--good:#1a7f37}
@media (prefers-color-scheme: dark){:root{--bg:#1b1b1d;--fg:#ececf0;--muted:#a0a0a8;--line:#3a3a40;--card:#252528;--mark:#6b5d00;--bad:#ff8a80;--good:#6fdc8c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:14px 18px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2}
header h1{font-size:16px;margin:0 0 8px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
select{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);max-width:100%}
.legend{color:var(--muted);font-size:13px;margin-top:8px}
mark{background:var(--mark);color:inherit;border-radius:3px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px 18px}
@media (max-width:800px){.cols{grid-template-columns:1fr}}
.pane{border:1px solid var(--line);border-radius:10px;min-width:0}
.pane h2{font-size:14px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line);background:var(--card);border-radius:10px 10px 0 0}
.stats{color:var(--muted);font-size:13px;padding:8px 12px;border-bottom:1px solid var(--line)}
.stats b.ok{color:var(--good)} .stats b.bad{color:var(--bad)}
.text{padding:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:75vh;overflow:auto}
.empty{color:var(--muted);font-style:italic}
</style></head><body>
<header><h1>Which extractor got the article right?</h1>
<div class="controls">
<label>Page <select id="url"></select></label>
<label>Left <select id="left"></select></label>
<label>Right <select id="right"></select></label>
</div>
<div class="legend"><mark>Yellow</mark> = this sentence is not found in the other column
(extra text such as menus or ads, or text the other side missed).</div></header>
<div class="cols"><div class="pane" id="paneL"></div><div class="pane" id="paneR"></div></div>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const esc = t => t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
function fill(sel, items, labelOf, chosen){
  sel.innerHTML = items.map(v => `<option value="${esc(v)}"${v===chosen?" selected":""}>${esc(labelOf(v))}</option>`).join("");
}
function highlight(text, marks){
  let out = "", pos = 0;
  for (const m of marks){
    const i = text.indexOf(m, pos);
    if (i < 0) continue;
    out += esc(text.slice(pos, i)) + "<mark>" + esc(m) + "</mark>";
    pos = i + m.length;
  }
  return out + esc(text.slice(pos));
}
function pane(el, url, name, other){
  const e = D.data[url][name];
  if (!e){ el.innerHTML = "<h2>"+esc(D.labels[name]||name)+"</h2><div class='text empty'>Not run for this page.</div>"; return; }
  const ok = e.status === "success";
  const meta = [e.title && ("title: "+e.title), e.author && ("author: "+e.author), e.date && ("date: "+e.date)].filter(Boolean).join(" | ");
  const marks = ((D.missing[url]||{})[name]||{})[other] || [];
  const body = e.text ? highlight(e.text, marks) : "<span class='empty'>(no content extracted)</span>";
  el.innerHTML = "<h2>"+esc(D.labels[name]||name)+"</h2>"
    + "<div class='stats'>status: <b class='"+(ok?"ok":"bad")+"'>"+esc(e.status)+"</b> &middot; "
    + e.chars+" chars &middot; "+e.words+" words &middot; junk phrases: "+e.junk
    + (meta ? "<br>"+esc(meta) : "") + "</div><div class='text'>"+body+"</div>";
}
function draw(){
  const u = $("url").value, l = $("left").value, r = $("right").value;
  pane($("paneL"), u, l, r); pane($("paneR"), u, r, l);
}
fill($("url"), D.urls, v => v, D.urls[0]);
function names(){ return D.order.filter(n => D.data[$("url").value][n]); }
function refill(){
  const n = names();
  const left = n.includes(D.left) ? D.left : n[0];
  const right = n.includes(D.right) ? D.right : (n[1] || n[0]);
  fill($("left"), n, v => D.labels[v]||v, left);
  fill($("right"), n, v => D.labels[v]||v, right);
  draw();
}
$("url").onchange = refill; $("left").onchange = draw; $("right").onchange = draw;
refill();
</script></body></html>
"""


def write_side_by_side(rows, path):
    """One self-contained page: full text of any two extractors, side by side,
    with the sentences that the other column lacks highlighted."""
    urls = list(dict.fromkeys(r["url"] for r in rows))
    order = [n for n in EXTRACTOR_ORDER if any(r["extractor"] == n for r in rows)]

    data, missing = {}, {}
    for url in urls:
        page = {r["extractor"]: r for r in rows if r["url"] == url}
        data[url] = {
            name: {
                "text": r["_text"], "status": r["status"], "chars": r["chars"],
                "words": r["words"], "junk": r["junk_total"], "title": r["title"],
                "author": r["author"], "date": r["date"],
            }
            for name, r in page.items()
        }
        missing[url] = {}
        for a, ra in page.items():
            if not ra["_text"]:
                continue
            missing[url][a] = {
                b: missing_sentences(ra["_text"], rb["_text"])
                for b, rb in page.items() if b != a and rb["_text"]
            }

    payload = {
        "urls": urls,
        "order": order,
        "labels": EXTRACTOR_LABELS,
        "data": data,
        "missing": missing,
        "left": "traf_balanced",
        "right": "crawl4ai_fit" if "crawl4ai_fit" in order else "current",
    }
    encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    Path(path).write_text(
        SIDE_BY_SIDE_TEMPLATE.replace("__DATA__", encoded), encoding="utf-8"
    )


def print_summary(rows):
    summary = summarize(rows)
    print("\n" + "=" * 72)
    print(f"{'Extractor':16} {'Success':>8} {'Avg chars':>10} "
          f"{'Avg junk':>9} {'Avg sec':>8}")
    print("-" * 72)
    for name in EXTRACTOR_ORDER:
        if name not in summary:
            continue
        item = summary[name]
        pages = item["pages"] or 1
        print(f"{name:16} {str(item['success']) + '/' + str(item['pages']):>8} "
              f"{item['chars'] // pages:>10} {item['junk'] / pages:>9.1f} "
              f"{item['seconds'] / pages:>8.2f}")


def print_scores(csv_path):
    """Average the hand-entered scores per extractor."""
    totals = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                values = [float(row[c]) for c in
                          ("completeness_1_5", "noise_1_5", "metadata_1_5")]
            except (ValueError, KeyError):
                continue  # this row has no scores yet
            item = totals.setdefault(row["extractor"], [0, 0.0, 0.0, 0.0])
            item[0] += 1
            for index, value in enumerate(values, start=1):
                item[index] += value

    if not totals:
        print("No scores found. Fill the three score columns in the CSV first.")
        return

    print(f"{'Extractor':16} {'Rated':>6} {'Complete':>9} {'Noise':>7} "
          f"{'Metadata':>9} {'Overall':>8}")
    print("-" * 60)
    ranking = []
    for name in EXTRACTOR_ORDER:
        if name not in totals:
            continue
        n, c, z, m = totals[name]
        overall = (c + z + m) / (3 * n)
        ranking.append((overall, name))
        print(f"{name:16} {n:>6} {c / n:>9.2f} {z / n:>7.2f} "
              f"{m / n:>9.2f} {overall:>8.2f}")
    top = max(score for score, _ in ranking)
    winners = [name for score, name in ranking if abs(score - top) < 1e-9]
    print(f"\nHighest overall average ({top:.2f} out of 5): {', '.join(winners)}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    if hasattr(sys.stdout, "reconfigure"):  # Hindi text in PowerShell
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("urls", nargs="*", help="article URLs")
    parser.add_argument("--file", help="text file with one URL per line")
    parser.add_argument("--from-db", type=int, metavar="N",
                        help="use N recent articles from the database")
    parser.add_argument("--crawl4ai", action="store_true",
                        help="also run Crawl4AI (must be installed)")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open side_by_side.html in the browser")
    parser.add_argument("--wait", type=float, default=1.0, metavar="SECONDS",
                        help="Crawl4AI: seconds to wait for JavaScript before "
                             "reading the page (default 1.0)")
    parser.add_argument("--no-sandbox", action="store_true",
                        help="start the Crawl4AI browser with --no-sandbox "
                             "(needed on Linux/Docker running as root)")
    parser.add_argument("--scores", metavar="CSV",
                        help="average the scores you filled into the CSV")
    parser.add_argument("--out-dir", default="extraction_results")
    args = parser.parse_args()

    if args.scores:
        print_scores(args.scores)
        return

    expected = {}
    urls = list(args.urls)
    if args.file:
        urls += read_url_file(args.file)
    if args.from_db:
        expected = urls_from_db(args.from_db)
        urls += list(expected)

    urls = list(dict.fromkeys(urls))
    if not urls:
        parser.error("give URLs, --file or --from-db")
    if len(urls) > 15:
        print(f"Note: {len(urls)} URLs is a lot to score by hand; "
              "5 to 10 is usually enough.")

    all_rows = []
    for number, url in enumerate(urls, start=1):
        print(f"[{number}/{len(urls)}] {url}")
        rows = [run_current(url)] + run_trafilatura_variants(url)
        all_rows.extend(rows)

    if args.crawl4ai:
        print("Running Crawl4AI (first run can be slow)...")
        crawled = run_crawl4ai(urls, args.no_sandbox, args.wait)
        for url, rows in crawled.items():
            all_rows.extend(rows)

    for url, info in expected.items():
        add_metadata_checks([r for r in all_rows if r["url"] == url], info)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(all_rows, out_dir / "extraction_results.csv")
    write_report(all_rows, expected, out_dir / "extraction_report.md")
    side_by_side = out_dir / "side_by_side.html"
    write_side_by_side(all_rows, side_by_side)

    print_summary(all_rows)
    print(f"\nSaved to {out_dir}/")
    print("  side_by_side.html      (full text of each extractor, next to each other)")
    print("  extraction_report.md   (numbers and summary)")
    print("  extraction_results.csv (fill in the three score columns, then run")
    print(f"      python scripts/compare_extraction.py --scores "
          f"{out_dir / 'extraction_results.csv'})")
    if not args.no_open:
        webbrowser.open(side_by_side.resolve().as_uri())


if __name__ == "__main__":
    main()