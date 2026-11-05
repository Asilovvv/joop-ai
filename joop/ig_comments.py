"""Instagram comments answered in Direct: «сколько стоит?» under a reel becomes a dialogue with the AI.

In Bishkek a salon sells in Instagram, and the first question is often a comment under a post, not a message.
Meta lets a business answer a comment privately, once, within seven days (a "private reply" addressed by the
comment id); from then on the person's Direct thread is an ordinary conversation. Code decides which comments
deserve a Direct message: a question (there is a «?») or one of the business's keywords («цена», «запись»…);
«Красиво!» is left alone. The AI answers the question as it would in Direct, a short public reply under the
comment («Ответили вам в Директ») tells the person where to look, and anything further is the usual dialogue.
Off by default (`Business.ig_comments`); needs the «comments» webhook field and the instagram_manage_comments
permission in the Meta app (docs/channels.md). Manychat charges from $39 a month for the same trigger.
"""

from __future__ import annotations

from .models import Business

DEFAULT_KEYWORDS = "цена, прайс, сколько, стоит, запись, записаться, свободно, окно, канча, баасы, жазыл"
DEFAULT_PUBLIC_REPLY = "Ответили вам в Директ"


def keywords(business: Business) -> list[str]:
    raw = business.ig_comment_keywords if business.ig_comment_keywords.strip() else DEFAULT_KEYWORDS
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


def wanted(business: Business, text: str) -> bool:
    """A comment worth a Direct message: the feature is on and the comment asks something."""
    if not business.ig_comments:
        return False
    t = (text or "").strip().lower()
    if not t:
        return False
    return "?" in t or any(k in t for k in keywords(business))
