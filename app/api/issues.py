"""Generate a newsletter on demand and read issues."""
import html
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.api.schemas import GenerateNow, IssueDetail, RunState
from app.api.security import require_api_key
from app.database.db import SessionLocal
from app.database.models import NewsletterArticle, NewsletterIssue
from app.services import user_preferences as prefs
from app.services.editorial_service import generate_editorial_issue
from app.services.html_renderer import THEME_META_NAME
from app.services.user_research import run_user_research

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/issues",
    tags=["issues"],
    dependencies=[Depends(require_api_key)],
)

# State of the latest on-demand run per user.
_runs: dict[int, dict] = {}
_runs_lock = threading.RLock()
_user_tasks: dict[int, str] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(name="generate_on_demand_issue_task")
def run_pipeline_task(user_id: int, research: bool = True) -> dict:
    """Celery background task: (research) + editorial pipeline. Never sends email."""
    try:
        if research:
            run_user_research(user_id)

        result = generate_editorial_issue(user_id)
        update = {
            "state": "finished",
            "status": result["status"],
            "issue_id": result.get("issue_id"),
            "error": None,
            "finished_at": _now().isoformat(),
        }
    except Exception as exc:
        logger.exception("On-demand run failed for user %s", user_id)
        update = {
            "state": "failed",
            "status": None,
            "issue_id": None,
            "error": f"{type(exc).__name__}: see the server log.",
            "finished_at": _now().isoformat(),
        }

    with _runs_lock:
        if user_id in _runs:
            _runs[user_id].update(
                state=update["state"],
                status=update["status"],
                issue_id=update["issue_id"],
                error=update["error"],
                finished_at=_now(),
            )

    return update


def get_run_state(user_id: int) -> dict:
    with _runs_lock:
        task_id = _user_tasks.get(user_id)
        in_memory = _runs.get(user_id)

        if task_id:
            try:
                res = AsyncResult(task_id, app=celery_app)
                if res.state in ("PENDING", "STARTED", "RETRY"):
                    return {
                        "state": "running",
                        "status": None,
                        "issue_id": None,
                        "error": None,
                        "task_id": task_id,
                        "started_at": in_memory.get("started_at") if in_memory else None,
                        "finished_at": None,
                    }
                elif res.state == "SUCCESS":
                    data = res.result or {}
                    finished_at = data.get("finished_at")
                    if isinstance(finished_at, str):
                        try:
                            finished_at = datetime.fromisoformat(finished_at)
                        except Exception:
                            finished_at = None
                    task_state = data.get("state", "finished")
                    return {
                        "state": task_state,
                        "status": data.get("status"),
                        "issue_id": data.get("issue_id"),
                        "error": data.get("error"),
                        "task_id": task_id,
                        "started_at": in_memory.get("started_at") if in_memory else None,
                        "finished_at": finished_at or (in_memory.get("finished_at") if in_memory else _now()),
                    }
                elif res.state == "FAILURE":
                    return {
                        "state": "failed",
                        "status": None,
                        "issue_id": None,
                        "error": "Run failed: see the server log.",
                        "task_id": task_id,
                        "started_at": in_memory.get("started_at") if in_memory else None,
                        "finished_at": in_memory.get("finished_at") if in_memory else _now(),
                    }
            except Exception:
                logger.exception("Could not retrieve Celery AsyncResult for %s", task_id)

        if in_memory:
            return dict(in_memory)
        return {"state": "idle"}


@router.post("/generate-now", response_model=RunState, status_code=202)
def generate_now(body: GenerateNow, background_tasks: BackgroundTasks):
    """Start the editorial pipeline for a user in the background via Celery.

    It can take minutes, so this returns at once (202). Poll
    GET /api/users/{id}/run-status, then open the issue preview.
    """
    preferences = prefs.get_user_preferences(body.user_id)

    if preferences is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if not preferences["is_active"]:
        raise HTTPException(status_code=409, detail="This user is inactive.")

    if not preferences["topics"]:
        raise HTTPException(status_code=409, detail="This user has no topics.")

    with _runs_lock:
        current = get_run_state(body.user_id)
        if current.get("state") == "running":
            raise HTTPException(
                status_code=409, detail="A run is already in progress."
            )

        _runs[body.user_id] = {
            "state": "running",
            "status": None,
            "issue_id": None,
            "error": None,
            "started_at": _now(),
            "finished_at": None,
        }
        state = dict(_runs[body.user_id])

    task = run_pipeline_task.delay(body.user_id, body.research)
    with _runs_lock:
        _user_tasks[body.user_id] = task.id
        state["task_id"] = task.id

    return state


def _get_issue(session, issue_id: int) -> NewsletterIssue:
    issue = session.get(NewsletterIssue, issue_id)

    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found.")

    return issue


@router.get("/{issue_id}", response_model=IssueDetail)
def get_issue(issue_id: int):
    with SessionLocal() as session:
        issue = _get_issue(session, issue_id)
        article_count = session.scalar(
            select(func.count(NewsletterArticle.id)).where(
                NewsletterArticle.newsletter_issue_id == issue_id
            )
        )

        try:
            feedback = json.loads(issue.editor_feedback or "null")
        except ValueError:
            feedback = None

        return IssueDetail(
            id=issue.id,
            user_id=issue.user_id,
            subject=issue.subject,
            status=issue.status,
            created_at=issue.created_at,
            sent_at=issue.sent_at,
            article_count=article_count or 0,
            revision_count=issue.revision_count,
            big_picture=issue.big_picture,
            editor_feedback=feedback if isinstance(feedback, dict) else None,
            has_html=bool(issue.html_body),
            preview_url=f"/api/issues/{issue.id}/preview",
        )


# The page is built by our own renderer (all text is escaped), but scripts
# and outside resources are blocked anyway as a second line of defence.
PREVIEW_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    ),
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
}


def _issue_document(issue: NewsletterIssue) -> str:
    """The issue's HTML email, or its text as a simple page if it has none."""
    if issue.html_body:
        return issue.html_body

    # Issues without HTML (for example very old ones): show the text.
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(issue.subject)}</title></head><body>"
        "<pre style='white-space:pre-wrap;font:16px/1.5 sans-serif;"
        f"max-width:700px;margin:24px auto'>{html.escape(issue.body)}</pre>"
        "</body></html>"
    )


@router.get("/{issue_id}/preview", response_class=HTMLResponse)
def preview_issue(issue_id: int):
    """The newsletter exactly as the HTML email, viewable in a browser."""
    with SessionLocal() as session:
        issue = _get_issue(session, issue_id)
        page = _issue_document(issue)

    return HTMLResponse(page, headers=PREVIEW_HEADERS)


# ---------------------------------------------------------------- live view

LIVE_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "static" / "live.html"
).read_text(encoding="utf-8")

# This page runs our own background script, so scripts are allowed for the
# page itself. The newsletter sits in a sandboxed frame without scripts.
LIVE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; img-src data:; frame-src about:"
    ),
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
}

_FOREST_MARKER = f'name="{THEME_META_NAME}" content="forest"'
_OPEN_LINKS_IN_NEW_TAB = '<base target="_blank">'
# Let the animated background show through the dark-green email.
_SEE_THROUGH = (
    "<style>"
    "html,body{background:transparent!important;background-image:none!important}"
    "body>table{background:transparent!important;background-image:none!important}"
    "table.container{background:rgba(6,48,36,.9)!important}"
    "</style>"
)
_PLACEHOLDER = re.compile(r"__(TITLE|DOC)__")


def _live_document(doc: str) -> str:
    """Prepare the email HTML to be shown on top of the live background."""
    extra = _OPEN_LINKS_IN_NEW_TAB

    # Only the dark-green theme is made see-through; a light email keeps its
    # own colours so that its dark text stays readable.
    if _FOREST_MARKER in doc:
        extra += _SEE_THROUGH

    if "</head>" in doc:
        return doc.replace("</head>", extra + "</head>", 1)

    return "<!doctype html><head>" + extra + "</head>" + doc


@router.get("/{issue_id}/live", response_class=HTMLResponse)
def live_issue(issue_id: int):
    """The newsletter on an animated background (browser only).

    Email programs cannot run animation, so this is the web edition of the
    same issue; the email itself only gets the matching colours.
    """
    with SessionLocal() as session:
        issue = _get_issue(session, issue_id)
        subject = issue.subject
        doc = _live_document(_issue_document(issue))

    values = {"TITLE": html.escape(subject), "DOC": html.escape(doc, quote=True)}
    # One pass over the template only, so the newsletter text is never
    # scanned for placeholders.
    page = _PLACEHOLDER.sub(lambda match: values[match.group(1)], LIVE_TEMPLATE)

    return HTMLResponse(page, headers=LIVE_HEADERS)
