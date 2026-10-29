"""Small, safe repairs for text written by the AI models.

Some models drop the space after a full stop ("India.No further details").
fix_spacing() repairs that one pattern only. It cannot repair words that
are glued together in the middle of a sentence, and it deliberately leaves
alone anything that could be legitimate, such as "U.S.Government",
"3.5", "Node.js" or "Dr.Smith".
"""
import re

# A full stop, "!" or "?" that follows at least two lowercase letters and is
# directly followed by a capitalised word (an uppercase letter and then a
# lowercase one).
_MISSING_SPACE = re.compile(r"(?<=[a-z]{2})([.!?])(?=[A-Z][a-z])")


def fix_spacing(text: str) -> str:
    """Insert the missing space between two sentences."""
    return _MISSING_SPACE.sub(r"\1 ", text)