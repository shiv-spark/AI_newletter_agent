import time

import requests

from app.config import settings


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def get_chat_completion(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 500,
) -> str:
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing from the environment."
        )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": settings.app_name,
    }

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    response = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=45,
            )

            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                break

            if attempt == MAX_RETRIES - 1:
                response.raise_for_status()

        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_RETRIES - 1:
                raise

        delay = INITIAL_RETRY_DELAY * (2 ** attempt)
        time.sleep(delay)

    data = response.json()

    choices = data.get("choices") or []

    if not choices:
        error_info = data.get("error", {})
        raise ValueError(
            "AI provider returned no choices. "
            f"Provider error: {error_info}"
        )

    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    finish_reason = choice.get("finish_reason")

    if isinstance(content, list):
        content = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
        )

    if not isinstance(content, str) or not content.strip():
        raise ValueError(
            "AI provider returned empty content. "
            f"Finish reason: {finish_reason}; "
            f"message fields: {list(message.keys())}; "
            f"refusal: {message.get('refusal')}"
        )

    return content.strip()