"""Input/output contracts for the four editorial agents.

Every agent returns one of these models, so a malformed LLM answer fails
validation instead of silently flowing into the next stage.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.agents.text_cleanup import fix_spacing


# --------------------------------------------------------------------------
# Curator Agent
# --------------------------------------------------------------------------

class ArticleScore(BaseModel):
    """Scores for one candidate article, each from 0 (worst) to 10 (best).

    The weighted total is computed in code, not by the LLM.
    """

    article_id: int
    relevance: int = Field(ge=0, le=10)
    impact: int = Field(ge=0, le=10)
    credibility: int = Field(ge=0, le=10)
    novelty: int = Field(ge=0, le=10)
    reject_reason: str | None = None
    reason: str = ""


class CuratorOutput(BaseModel):
    scores: list[ArticleScore]


# --------------------------------------------------------------------------
# Analyst Agent
# --------------------------------------------------------------------------

class StoryInsight(BaseModel):
    article_id: int
    what_happened: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    # True when the insight goes beyond what the source states.
    is_speculative: bool = False

    @field_validator("what_happened", "why_it_matters", "impact")
    @classmethod
    def _fix_missing_spaces(cls, value):
        return fix_spacing(value)


class AnalystOutput(BaseModel):
    big_picture: str = Field(min_length=1)
    stories: list[StoryInsight] = Field(min_length=1)

    @field_validator("big_picture")
    @classmethod
    def _fix_big_picture_spacing(cls, value):
        return fix_spacing(value)

    @model_validator(mode="after")
    def _unique_story_ids(self):
        ids = [story.article_id for story in self.stories]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate article_id in analyst stories.")
        return self


# --------------------------------------------------------------------------
# Writer Agent
# --------------------------------------------------------------------------

class WrittenStory(BaseModel):
    article_id: int
    headline: str = Field(min_length=1)
    what_happened: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    # Only a number or finding that the source supports; None otherwise.
    key_fact: str | None = None

    @field_validator("key_fact", mode="before")
    @classmethod
    def _number_key_fact_becomes_text(cls, value):
        # Models sometimes answer with a bare number such as 450000000.
        # Turn it into text; the Writer then checks it against the source.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value

    @field_validator("headline", "what_happened", "why_it_matters")
    @classmethod
    def _fix_missing_spaces(cls, value):
        return fix_spacing(value)

    @field_validator("key_fact")
    @classmethod
    def _blank_key_fact_is_none(cls, value):
        if value is not None and not value.strip():
            return None
        return value


class WriterOutput(BaseModel):
    subject: str = Field(min_length=1)
    stories: list[WrittenStory] = Field(min_length=1)

    @field_validator("subject")
    @classmethod
    def _fix_subject_spacing(cls, value):
        return fix_spacing(value)

    @model_validator(mode="after")
    def _unique_story_ids(self):
        ids = [story.article_id for story in self.stories]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate article_id in written stories.")
        return self


# --------------------------------------------------------------------------
# Editor-in-Chief Agent
# --------------------------------------------------------------------------

class EditorIssue(BaseModel):
    # None means the problem is with the subject line or the whole issue.
    article_id: int | None = None
    problem: str = Field(min_length=1)
    # Exact correction the Writer must apply.
    correction: str = Field(min_length=1)


_NO_PROBLEM = re.compile(
    r"^\s*(no (problems?|issues?|errors?)( (was |were )?found)?|none|n/?a)\s*[.!]?\s*$",
    re.IGNORECASE,
)

DEFAULT_CORRECTION = "Fix this problem using only facts from the source text."


class EditorVerdict(BaseModel):
    status: Literal["approved", "rejected", "needs_review"]
    issues: list[EditorIssue] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _tidy_issues(cls, data):
        """Weak models sometimes list "No problems found." as an issue, or
        forget the correction text. A plain "no problem" entry is dropped.
        A real problem without a correction is KEPT (so it still blocks
        approval) and gets a generic correction.
        """
        if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
            return data

        tidy = []

        for item in data["issues"]:
            if not isinstance(item, dict):
                tidy.append(item)
                continue

            problem = str(item.get("problem") or "")
            correction = str(item.get("correction") or "").strip()

            if not correction:
                if _NO_PROBLEM.match(problem):
                    continue

                item = {**item, "correction": DEFAULT_CORRECTION}

            tidy.append(item)

        return {**data, "issues": tidy}

    @model_validator(mode="after")
    def _rejection_needs_issues(self):
        if self.status == "rejected" and not self.issues:
            raise ValueError(
                "A rejected verdict must list at least one issue."
            )
        return self


# --------------------------------------------------------------------------
# Writer Agent: subject-line revision
# --------------------------------------------------------------------------

class SubjectRevision(BaseModel):
    subject: str = Field(min_length=1)