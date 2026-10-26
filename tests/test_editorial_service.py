import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import requests
from sqlalchemy import delete, func, select

from app.agents.editor import ReviewResult
from app.agents.schemas import (
    AnalystOutput,
    StoryInsight,
    WriterOutput,
    WrittenStory,
)
from app.database.db import SessionLocal
from app.database.models import (
    Article,
    NewsletterArticle,
    NewsletterIssue,
    User,
    UserTopic,
)
from app.services import editorial_service
from app.services.delivery_service import send_newsletter
from app.services.editorial_service import generate_editorial_issue

FACT_TEXT = "The company said 42 percent of teams use AI tools. " * 12


@pytest.fixture
def world():
    """A user who follows a unique topic, plus four matching articles.

    The topic is a unique made-up word, so articles collected from real
    feeds can never match it and the tests only see their own articles.
    """
    tag = uuid.uuid4().hex[:8]
    topic = f"zq{tag}"

    with SessionLocal() as session:
        user = User(email=f"editorial-{tag}@example.com", language="en")
        session.add(user)
        session.flush()
        session.add(UserTopic(user_id=user.id, topic=topic))

        articles = []

        for number in range(4):
            article = Article(
                title=f"Story number {number} {topic}",
                url=f"https://news.example/{tag}/{number}",
                canonical_url=f"https://news.example/{tag}/{number}",
                source_name="Test Wire",
                content_hash=f"{tag}-{number}",
                summary=f"Summary {number} about {topic}.",
                content=FACT_TEXT,
                published_at=datetime.now(timezone.utc) - timedelta(hours=number),
            )
            session.add(article)
            articles.append(article)

        session.commit()
        user_id = user.id
        article_ids = [article.id for article in articles]

    yield {"user_id": user_id, "article_ids": article_ids, "tag": tag}

    with SessionLocal() as session:
        issue_ids = select(NewsletterIssue.id).where(
            NewsletterIssue.user_id == user_id
        )
        session.execute(
            delete(NewsletterArticle).where(
                NewsletterArticle.newsletter_issue_id.in_(issue_ids)
            )
        )
        session.execute(
            delete(NewsletterIssue).where(NewsletterIssue.user_id == user_id)
        )
        session.execute(delete(UserTopic).where(UserTopic.user_id == user_id))
        session.execute(delete(Article).where(Article.id.in_(article_ids)))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def issues_of(user_id):
    with SessionLocal() as session:
        return session.scalars(
            select(NewsletterIssue)
            .where(NewsletterIssue.user_id == user_id)
            .order_by(NewsletterIssue.id)
        ).all()


def linked_article_ids(issue_id):
    with SessionLocal() as session:
        return set(
            session.scalars(
                select(NewsletterArticle.article_id).where(
                    NewsletterArticle.newsletter_issue_id == issue_id
                )
            ).all()
        )


# ---------------------------------------------------------------------------
# Fake agents (the real agents have their own tests)
# ---------------------------------------------------------------------------

def install_agents(monkeypatch, curate=3, review_status="approved", **review_kwargs):
    def fake_curate(candidates, topics):
        return [
            dict(c, curator_score=8.0, curator_reason="ok", limited_source=False)
            for c in candidates[:curate]
        ]

    def fake_analyze(stories, topics):
        return AnalystOutput(
            big_picture="Big picture text.",
            stories=[
                StoryInsight(
                    article_id=s["id"], what_happened="a",
                    why_it_matters="b", impact="c",
                )
                for s in stories
            ],
        )

    def fake_write(stories, analysis, topics, language="en"):
        return WriterOutput(
            subject="AI news today",
            stories=[
                WrittenStory(
                    article_id=s["id"],
                    headline=s["title"],
                    what_happened="First sentence here. Second sentence here.",
                    why_it_matters="It matters.",
                )
                for s in stories
            ],
        )

    def fake_review(stories, output, language="en"):
        kept = review_kwargs.pop("stories", output.stories)
        return ReviewResult(
            status=review_status,
            subject=output.subject,
            stories=kept,
            **review_kwargs,
        )

    monkeypatch.setattr(editorial_service, "curate_articles", fake_curate)
    monkeypatch.setattr(editorial_service, "analyze_stories", fake_analyze)
    monkeypatch.setattr(editorial_service, "write_newsletter", fake_write)
    monkeypatch.setattr(editorial_service, "review_and_revise", fake_review)


# ---------------------------------------------------------------------------
# Saving the issue
# ---------------------------------------------------------------------------

def test_approved_issue_is_saved_with_html_and_article_links(world, monkeypatch):
    install_agents(monkeypatch)

    result = generate_editorial_issue(world["user_id"])

    assert result["status"] == "approved"
    assert result["article_count"] == 3

    issue = issues_of(world["user_id"])[0]

    assert issue.status == "approved"
    assert issue.subject == "AI news today"
    assert "<html" in issue.html_body
    assert "AI news today" in issue.body
    assert issue.big_picture == "Big picture text."
    assert json.loads(issue.editor_feedback)["status"] == "approved"
    assert issue.revision_count == 0
    assert len(linked_article_ids(issue.id)) == 3


def test_articles_of_an_approved_issue_are_not_offered_again(world, monkeypatch):
    install_agents(monkeypatch)

    generate_editorial_issue(world["user_id"])
    second = generate_editorial_issue(world["user_id"])

    # Only one article is left, so there are not enough stories.
    assert second["status"] == "not_enough_stories"
    assert second["found"] == 1
    assert len(issues_of(world["user_id"])) == 1


def test_too_few_stories_saves_nothing(world, monkeypatch):
    install_agents(monkeypatch, curate=2)

    result = generate_editorial_issue(world["user_id"])

    assert result["status"] == "not_enough_stories"
    assert result["required"] == 3
    assert issues_of(world["user_id"]) == []


def test_rejected_issue_is_saved_but_can_never_be_sent(world, monkeypatch):
    install_agents(
        monkeypatch, review_status="rejected", stories=[], note="Too many errors."
    )

    result = generate_editorial_issue(world["user_id"])

    assert result["status"] == "rejected"

    issue = issues_of(world["user_id"])[0]

    assert issue.status == "rejected"
    assert issue.body == "Too many errors."
    assert issue.html_body is None

    with patch("app.services.delivery_service.send_email") as email:
        sent = send_newsletter(issue.id)

    assert sent["status"] == "not_sendable"
    email.assert_not_called()


def test_needs_review_issue_is_readable_but_never_sent(world, monkeypatch):
    install_agents(monkeypatch, review_status="needs_review", note="Editor unsure.")

    generate_editorial_issue(world["user_id"])
    issue = issues_of(world["user_id"])[0]

    assert issue.status == "needs_review"
    assert "<html" in issue.html_body  # a person can read it

    with patch("app.services.delivery_service.send_email") as email:
        sent = send_newsletter(issue.id)

    assert sent["status"] == "not_sendable"
    email.assert_not_called()


def test_big_picture_is_left_out_when_stories_were_dropped(world, monkeypatch):
    def keep_two(stories):
        return stories[:2]

    install_agents(monkeypatch)
    original_review = editorial_service.review_and_revise

    def review_with_drop(stories, output, language="en"):
        result = original_review(stories, output, language)
        result.stories = keep_two(result.stories)
        result.big_picture_stale = True
        result.dropped_article_ids = [stories[2]["id"]]
        return result

    monkeypatch.setattr(editorial_service, "review_and_revise", review_with_drop)

    generate_editorial_issue(world["user_id"])
    issue = issues_of(world["user_id"])[0]

    assert issue.big_picture is None
    assert "Big picture text." not in issue.html_body
    assert len(linked_article_ids(issue.id)) == 2


def test_articles_of_a_rejected_issue_can_be_used_again(world, monkeypatch):
    install_agents(
        monkeypatch, review_status="rejected", stories=[], note="No."
    )
    generate_editorial_issue(world["user_id"])

    candidates = editorial_service.load_candidates(world["user_id"])["candidates"]

    assert len(candidates) == 4


# ---------------------------------------------------------------------------
# Failures: nothing is saved, nothing can be sent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("failing", ["analyze_stories", "write_newsletter", "review_and_revise"])
def test_ai_failure_saves_nothing(world, monkeypatch, failing):
    install_agents(monkeypatch)

    def broken(*args, **kwargs):
        raise ValueError("AI did not answer.")

    monkeypatch.setattr(editorial_service, failing, broken)

    result = generate_editorial_issue(world["user_id"])

    assert result["status"] == "editorial_error"
    assert "AI did not answer." in result["error"]
    assert issues_of(world["user_id"]) == []


def test_network_failure_saves_nothing(world, monkeypatch):
    install_agents(monkeypatch)

    def offline(*args, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(editorial_service, "review_and_revise", offline)

    assert generate_editorial_issue(world["user_id"])["status"] == "editorial_error"
    assert issues_of(world["user_id"]) == []


def test_missing_api_key_is_not_hidden(world, monkeypatch):
    install_agents(monkeypatch)

    def no_key(*args, **kwargs):
        raise RuntimeError("OPENROUTER_API_KEY is missing")

    monkeypatch.setattr(editorial_service, "analyze_stories", no_key)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        generate_editorial_issue(world["user_id"])


def test_unknown_inactive_and_topicless_users(world):
    assert generate_editorial_issue(-1)["status"] == "user_not_found"

    with SessionLocal() as session:
        session.get(User, world["user_id"]).is_active = False
        session.commit()

    assert generate_editorial_issue(world["user_id"])["status"] == "inactive_user"

    with SessionLocal() as session:
        user = session.get(User, world["user_id"])
        user.is_active = True
        session.execute(delete(UserTopic).where(UserTopic.user_id == user.id))
        session.commit()

    assert generate_editorial_issue(world["user_id"])["status"] == "no_topics"


def test_topic_without_matching_articles(world):
    with SessionLocal() as session:
        session.execute(delete(UserTopic).where(UserTopic.user_id == world["user_id"]))
        session.add(UserTopic(user_id=world["user_id"], topic="Zebra"))
        session.commit()

    assert generate_editorial_issue(world["user_id"])["status"] == "no_new_articles"


# ---------------------------------------------------------------------------
# End to end: real agents, scripted AI answers, then sending
# ---------------------------------------------------------------------------

def listed(prompt, label):
    """The JSON list that follows a label such as 'Stories:' in a prompt."""
    return json.loads(prompt.split(label + "\n", 1)[1].split("\n\n", 1)[0])


def scripted_ai(editor_answers):
    """Fake AI that answers each agent with valid JSON."""
    editor_calls = iter(editor_answers)

    def fake(system_prompt, user_prompt, max_tokens=500, model=None):
        if "Curator of a professional" in system_prompt:
            ids = [c["id"] for c in listed(user_prompt, "Candidates:")]
            return json.dumps({"scores": [
                {"article_id": i, "relevance": 8, "impact": 7, "credibility": 6,
                 "novelty": 7, "reject_reason": None, "reason": "good"}
                for i in ids
            ]})

        if "Analyst of a professional" in system_prompt:
            ids = [s["id"] for s in listed(user_prompt, "Stories:")]
            return json.dumps({"big_picture": "AI use is growing.", "stories": [
                {"article_id": i, "what_happened": "x", "why_it_matters": "y",
                 "impact": "z", "is_speculative": False}
                for i in ids
            ]})

        if "Write the newsletter from the analysis" in system_prompt:
            ids = [s["id"] for s in listed(user_prompt, "Stories:")]
            return json.dumps({"subject": "AI news today", "stories": [
                {"article_id": i, "headline": f"Headline {i}",
                 "what_happened": "The firm launched a tool. Teams adopted it fast.",
                 "why_it_matters": "Adoption is rising.",
                 "key_fact": "42 percent of teams use AI tools"}
                for i in ids
            ]})

        if "rejected one of your stories" in system_prompt:
            return json.dumps({
                "article_id": 0, "headline": "Fixed headline",
                "what_happened": "The firm launched a tool. Teams adopted it fast.",
                "why_it_matters": "Adoption is rising.", "key_fact": None,
            })

        if "Editor-in-Chief of a professional" in system_prompt:
            return next(editor_calls)

        raise AssertionError("Unexpected agent prompt")

    return fake


def test_full_pipeline_then_sending(world):
    ai = scripted_ai(['{"status": "approved", "issues": []}'])

    with patch("app.agents.llm_client.get_chat_completion", ai):
        result = generate_editorial_issue(world["user_id"])

    assert result["status"] == "approved"
    assert result["article_count"] == 4

    issue = issues_of(world["user_id"])[0]

    assert "42 percent of teams use AI tools" in issue.html_body
    assert "AI use is growing." in issue.html_body

    with patch(
        "app.services.delivery_service.send_email",
        return_value={"success": True, "message_id": "m-1"},
    ) as email:
        sent = send_newsletter(issue.id)

    assert sent["status"] == "sent"
    assert "<html" in email.call_args.kwargs["html"]
    assert "AI news today" in email.call_args.kwargs["body"]
    assert issues_of(world["user_id"])[0].status == "sent"


def test_full_pipeline_with_one_correction(world):
    editor = [
        json.dumps({"status": "rejected", "issues": [
            {"article_id": 0, "problem": "Wrong headline", "correction": "Fix it"}
        ]}),
        '{"status": "approved", "issues": []}',
    ]

    with patch("app.agents.llm_client.get_chat_completion", scripted_ai(editor)):
        result = generate_editorial_issue(world["user_id"])

    assert result["status"] == "approved"
    assert result["revision_count"] == 1

    issue = issues_of(world["user_id"])[0]

    assert "Fixed headline" in issue.html_body
    assert json.loads(issue.editor_feedback)["revision_count"] == 1