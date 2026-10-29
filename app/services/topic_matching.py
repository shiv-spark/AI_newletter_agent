"""Match a user's topic against article titles and summaries."""
import re

SPECIAL_CHARACTERS = re.compile(r"([\\.^$|?*+()\[\]{}])")


def build_topic_pattern(topic: str) -> str:
    """Build a regex that matches the topic as a whole word or phrase.

    "AI" matches "New AI model" but not "Spain" or "said".
    """
    topic = " ".join(topic.split())

    if not topic:
        raise ValueError("Topic cannot be empty.")

    # Treat special characters such as + or . as normal text.
    pattern = SPECIAL_CHARACTERS.sub(r"\\\1", topic)
    pattern = pattern.replace(" ", r"\s+")

    # Word boundaries only next to plain English letters or digits,
    # so topics like "C++" or Hindi topics still work.
    if topic[0].isascii() and topic[0].isalnum():
        pattern = r"\m" + pattern

    if topic[-1].isascii() and topic[-1].isalnum():
        pattern = pattern + r"\M"

    return pattern
