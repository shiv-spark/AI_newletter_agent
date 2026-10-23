
from urllib.parse import urlparse


def validate_newsletter(
    subject: str,
    body: str,
    articles: list[dict],
) -> dict:
    """Validate a newsletter before it can be sent."""

    errors = []
    warnings = []

    # 1. Validate subject
    if not isinstance(subject, str) or not subject.strip():
        errors.append("Newsletter subject is missing.")

    # 2. Validate body
    if not isinstance(body, str) or not body.strip():
        errors.append("Newsletter body is empty.")

    # 3. Validate article list
    if not isinstance(articles, list) or not articles:
        errors.append("Newsletter must contain at least one article.")
        articles = []

    seen_ids = set()
    valid_article_count = 0

    for index, article in enumerate(articles, start=1):
        if not isinstance(article, dict):
            errors.append(f"Article {index} is not a valid object.")
            continue

        # Article ID
        article_id = article.get("id")

        if article_id is None:
            errors.append(f"Article {index} is missing its ID.")
        elif article_id in seen_ids:
            errors.append(f"Duplicate article ID found: {article_id}.")
        else:
            seen_ids.add(article_id)

        # Article title
        title = article.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"Article {index} has no title.")

        # Article URL
        url = article.get("url")

        if not isinstance(url, str) or not url.strip():
            errors.append(f"Article {index} has no URL.")
        else:
            try:
                parsed_url = urlparse(url.strip())

                if (
                    parsed_url.scheme not in ("http", "https")
                    or not parsed_url.hostname
                    or any(char.isspace() for char in url.strip())
                ):
                    errors.append(
                        f"Article {index} has an invalid HTTP/HTTPS URL."
                    )
                else:
                    # Accessing port also detects malformed port numbers.
                    _ = parsed_url.port
            except ValueError:
                errors.append(
                    f"Article {index} has an invalid HTTP/HTTPS URL."
                )

        # AI-generated summary
        summary = article.get("ai_summary")

        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"Article {index} has no AI summary.")

        # Source name
        source = article.get("source_name")

        if not isinstance(source, str) or not source.strip():
            warnings.append(
                f"Article {index} does not have a source name."
            )

        if (
            isinstance(title, str)
            and title.strip()
            and isinstance(url, str)
            and url.strip()
            and isinstance(summary, str)
            and summary.strip()
        ):
            valid_article_count += 1

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "article_count": len(articles),
        "valid_article_count": valid_article_count,
    }
