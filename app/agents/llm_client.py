# import json
# import logging
# import re
# import time

# import requests
# from pydantic import BaseModel, ValidationError

# from app.config import settings

# logger = logging.getLogger(__name__)


# OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# MAX_RETRIES = 3
# INITIAL_RETRY_DELAY = 2

# RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# def get_chat_completion(
#     system_prompt: str,
#     user_prompt: str,
#     max_tokens: int = 500,
#     model: str | None = None,
# ) -> str:
#     if not settings.openrouter_api_key:
#         raise RuntimeError(
#             "OPENROUTER_API_KEY is missing from the environment."
#         )

#     headers = {
#         "Authorization": f"Bearer {settings.openrouter_api_key}",
#         "Content-Type": "application/json",
#         "X-OpenRouter-Title": settings.app_name,
#     }

#     payload = {
#         "model": model or settings.openrouter_model,
#         "messages": [
#             {"role": "system", "content": system_prompt},
#             {"role": "user", "content": user_prompt},
#         ],
#         "temperature": 0.2,
#         "max_tokens": max_tokens,
#         "chat_template_kwargs": {"enable_thinking": False},
#     }

#     response = None

#     for attempt in range(MAX_RETRIES):
#         try:
#             response = requests.post(
#                 OPENROUTER_URL,
#                 headers=headers,
#                 json=payload,
#                 timeout=45,
#             )

#             if response.status_code not in RETRYABLE_STATUS_CODES:
#                 response.raise_for_status()
#                 break

#             if attempt == MAX_RETRIES - 1:
#                 response.raise_for_status()

#         except (requests.Timeout, requests.ConnectionError):
#             if attempt == MAX_RETRIES - 1:
#                 raise

#         delay = INITIAL_RETRY_DELAY * (2 ** attempt)
#         time.sleep(delay)

#     data = response.json()

#     choices = data.get("choices") or []

#     if not choices:
#         error_info = data.get("error", {})
#         raise ValueError(
#             "AI provider returned no choices. "
#             f"Provider error: {error_info}"
#         )

#     choice = choices[0]
#     message = choice.get("message") or {}
#     content = message.get("content")
#     finish_reason = choice.get("finish_reason")

#     if isinstance(content, list):
#         content = "\n".join(
#             block.get("text", "")
#             for block in content
#             if isinstance(block, dict)
#             and block.get("type") == "text"
#         )

#     if not isinstance(content, str) or not content.strip():
#         raise ValueError(
#             "AI provider returned empty content. "
#             f"Finish reason: {finish_reason}; "
#             f"message fields: {list(message.keys())}; "
#             f"refusal: {message.get('refusal')}"
#         )

#     return content.strip()


# def _extract_json(raw: str) -> str:
#     """Strip Markdown fences and surrounding text around a JSON object."""
#     text = raw.strip()

#     fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
#     if fenced:
#         text = fenced.group(1).strip()

#     start = text.find("{")
#     end = text.rfind("}")

#     if start != -1 and end > start:
#         return text[start : end + 1]

#     return text


# def get_structured_completion(
#     system_prompt: str,
#     user_prompt: str,
#     schema: type[BaseModel],
#     max_tokens: int = 2000,
#     model: str | None = None,
#     max_attempts: int = 3,
# ) -> BaseModel:
#     """Call the LLM and return a validated Pydantic object.

#     If the answer is not valid JSON or does not match the schema, the
#     error is sent back to the model and the call is retried. After
#     max_attempts failures a ValueError is raised.
#     Setup errors (for example a missing API key) are not retried.
#     """
#     if max_attempts < 1:
#         raise ValueError("max_attempts must be at least 1.")

#     prompt = user_prompt
#     last_error: Exception | None = None

#     for attempt in range(1, max_attempts + 1):
#         response = get_chat_completion(
#             system_prompt,
#             prompt,
#             max_tokens=max_tokens,
#             model=model,
#         )

#         try:
#             return schema.model_validate(
#                 json.loads(_extract_json(response))
#             )
#         except (json.JSONDecodeError, ValidationError) as exc:
#             last_error = exc
#             logger.warning(
#                 "Structured output attempt %s/%s failed for %s: %s",
#                 attempt,
#                 max_attempts,
#                 schema.__name__,
#                 exc,
#             )
#             prompt = (
#                 f"{user_prompt}\n\n"
#                 "Your previous answer was invalid:\n"
#                 f"{str(exc)[:500]}\n"
#                 "Return ONLY one valid JSON object that matches the "
#                 "required format. No Markdown fences, no extra text."
#             )

#     raise ValueError(
#         f"AI did not return valid {schema.__name__} after "
#         f"{max_attempts} attempts: {last_error}"
#     )


import json
import logging
import re
import time

import requests
from pydantic import BaseModel, ValidationError

from app.config import settings

logger = logging.getLogger(__name__)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2

REQUEST_TIMEOUT = 90

# When a JSON answer is invalid, the most common cause is that it was cut
# off. The retry gets twice the token budget, up to this limit.
MAX_RETRY_TOKENS = 8000

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def get_chat_completion(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 500,
    model: str | None = None,
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
        "model": model or settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        # Reasoning ("thinking") tokens count against max_tokens and can
        # leave too little room for the JSON answer. OpenRouter ignores
        # this for models that cannot turn reasoning off.
        "reasoning": {"enabled": False},
        "chat_template_kwargs": {"enable_thinking": False},
    }

    response = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
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

    if finish_reason == "length":
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        logger.warning(
            "AI answer was cut off at max_tokens=%s (completion tokens: %s, "
            "reasoning tokens: %s).",
            max_tokens,
            usage.get("completion_tokens"),
            details.get("reasoning_tokens"),
        )

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


def _extract_json(raw: str) -> str:
    """Strip Markdown fences and surrounding text around a JSON object."""
    text = raw.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end > start:
        return text[start : end + 1]

    return text


def parse_json_object(raw: str):
    """Parse the JSON object in a model answer, forgiving small typos.

    Handles Markdown fences, text around the object, extra characters
    AFTER the object (a stray closing brace), and a missing final closing
    brace after a closed list. It never invents content: an answer that
    is cut off in the middle (including an open list) still fails.
    """
    text = raw.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("{")
    candidate = text[start:] if start != -1 else text

    decoder = json.JSONDecoder()

    try:
        return decoder.raw_decode(candidate)[0]
    except json.JSONDecodeError as first_error:
        # Only when the last list is properly CLOSED and just the final
        # brace is missing. A list that was cut off open is never closed
        # for the model: that could turn "still writing" into "no issues".
        stripped = candidate.rstrip()

        if stripped.endswith("]"):
            try:
                return decoder.raw_decode(stripped + "}")[0]
            except json.JSONDecodeError:
                pass

        raise first_error


def get_structured_completion(
    system_prompt: str,
    user_prompt: str,
    schema: type[BaseModel],
    max_tokens: int = 2000,
    model: str | None = None,
    max_attempts: int = 3,
) -> BaseModel:
    """Call the LLM and return a validated Pydantic object.

    If the answer is not valid JSON or does not match the schema, the
    error is sent back to the model and the call is retried. After
    max_attempts failures a ValueError is raised.
    Setup errors (for example a missing API key) are not retried.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    prompt = user_prompt
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        response = get_chat_completion(
            system_prompt,
            prompt,
            max_tokens=max_tokens,
            model=model,
        )

        try:
            return schema.model_validate(parse_json_object(response))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            logger.warning(
                "Structured output attempt %s/%s failed for %s: %s",
                attempt,
                max_attempts,
                schema.__name__,
                exc,
            )
            logger.warning(
                "Raw answer was %s characters. Start: %r ... End: %r",
                len(response),
                response[:150],
                response[-150:],
            )
            # A cut-off answer is the usual cause, so allow a longer one.
            max_tokens = min(max_tokens * 2, MAX_RETRY_TOKENS)
            prompt = (
                f"{user_prompt}\n\n"
                "Your previous answer was invalid:\n"
                f"{str(exc)[:500]}\n"
                "Return ONLY one valid JSON object that matches the "
                "required format. No Markdown fences, no extra text."
            )

    raise ValueError(
        f"AI did not return valid {schema.__name__} after "
        f"{max_attempts} attempts: {last_error}"
    )