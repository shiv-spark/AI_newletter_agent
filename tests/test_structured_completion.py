import pytest

from app.agents import llm_client
from app.agents.schemas import EditorVerdict


def fake_replies(monkeypatch, replies):
    """Make get_chat_completion return the given replies one by one."""
    calls = []

    def fake(system_prompt, user_prompt, max_tokens=500, model=None):
        calls.append({"prompt": user_prompt, "model": model})
        return replies[len(calls) - 1]

    monkeypatch.setattr(llm_client, "get_chat_completion", fake)
    return calls


def test_valid_json_is_parsed(monkeypatch):
    fake_replies(monkeypatch, ['{"status": "approved", "issues": []}'])

    result = llm_client.get_structured_completion(
        "system", "user", EditorVerdict
    )

    assert result.status == "approved"


def test_markdown_fences_and_extra_text_are_removed(monkeypatch):
    fake_replies(
        monkeypatch,
        ['Here you go:\n```json\n{"status": "approved"}\n```\nDone.'],
    )

    result = llm_client.get_structured_completion(
        "system", "user", EditorVerdict
    )

    assert result.status == "approved"


def test_invalid_answer_is_retried_with_the_error(monkeypatch):
    calls = fake_replies(
        monkeypatch,
        ["not json at all", '{"status": "approved"}'],
    )

    result = llm_client.get_structured_completion(
        "system", "user", EditorVerdict
    )

    assert result.status == "approved"
    assert len(calls) == 2
    assert "previous answer was invalid" in calls[1]["prompt"]


def test_schema_violation_is_retried(monkeypatch):
    calls = fake_replies(
        monkeypatch,
        ['{"status": "rejected", "issues": []}', '{"status": "approved"}'],
    )

    result = llm_client.get_structured_completion(
        "system", "user", EditorVerdict
    )

    assert result.status == "approved"
    assert len(calls) == 2


def test_gives_up_after_max_attempts(monkeypatch):
    calls = fake_replies(monkeypatch, ["bad", "bad", "bad"])

    with pytest.raises(ValueError, match="EditorVerdict"):
        llm_client.get_structured_completion(
            "system", "user", EditorVerdict, max_attempts=3
        )

    assert len(calls) == 3


def test_missing_api_key_is_not_retried(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "openrouter_api_key", "")

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        llm_client.get_structured_completion(
            "system", "user", EditorVerdict
        )


def test_model_override_is_passed_through(monkeypatch):
    calls = fake_replies(monkeypatch, ['{"status": "approved"}'])

    llm_client.get_structured_completion(
        "system", "user", EditorVerdict, model="some/strong-model"
    )

    assert calls[0]["model"] == "some/strong-model"


def test_retry_after_invalid_answer_gets_more_tokens(monkeypatch):
    budgets = []
    replies = iter(['{"status": "approved", "issues": [', '{"status": "approved"}'])

    def fake(system_prompt, user_prompt, max_tokens=500, model=None):
        budgets.append(max_tokens)
        return next(replies)

    monkeypatch.setattr(llm_client, "get_chat_completion", fake)

    result = llm_client.get_structured_completion(
        "system", "user", EditorVerdict, max_tokens=2000
    )

    assert result.status == "approved"
    assert budgets == [2000, 4000]


def test_token_budget_on_retry_is_capped(monkeypatch):
    budgets = []

    def fake(system_prompt, user_prompt, max_tokens=500, model=None):
        budgets.append(max_tokens)
        return "bad"

    monkeypatch.setattr(llm_client, "get_chat_completion", fake)

    with pytest.raises(ValueError):
        llm_client.get_structured_completion(
            "system", "user", EditorVerdict, max_tokens=6000, max_attempts=3
        )

    assert budgets == [6000, llm_client.MAX_RETRY_TOKENS, llm_client.MAX_RETRY_TOKENS]