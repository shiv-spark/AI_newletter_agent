"""The brand name that appears on every newsletter.

It is shown in three places so recipients always see who sent it:
the sender name, the subject line ("Sparkbrains | title") and the header
and footer inside the email. Set it with NEWSLETTER_BRAND in .env.
"""
import re

from app.config import settings

# Characters that could break an email header or the HTML.
_UNSAFE = re.compile(r'[<>"\r\n]')


def brand_name() -> str:
    return _UNSAFE.sub("", settings.newsletter_brand or "").strip()


def branded_subject(subject: str) -> str:
    """"Short title" -> "Sparkbrains | Short title" (once, never twice)."""
    subject = " ".join((subject or "").split())
    brand = brand_name()

    if not subject or not brand or subject.lower().startswith(brand.lower()):
        return subject

    return f"{brand} | {subject}"


def sender_address(from_email: str) -> str:
    """"news@x.com" -> "Sparkbrains <news@x.com>"; "Name <a@b.c>" stays."""
    from_email = (from_email or "").strip()
    brand = brand_name()

    if not brand or "<" in from_email:
        return from_email

    return f"{brand} <{from_email}>"
