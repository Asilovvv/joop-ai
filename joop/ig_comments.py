"""Instagram comments answered in Direct: «сколько стоит?» under a reel becomes a dialogue with the AI.

In Bishkek a salon sells in Instagram, and the first question is often a comment under a post, not a message.
Meta lets a business answer a comment privately, once, within seven days (a "private reply" addressed by the
comment id); from then on the person's Direct thread is an ordinary conversation. Code decides which comments
deserve a Direct message: a question (there is a «?») or one of the business's keywords («цена», «запись»…) at
the start of a word; «Красиво!», «Записалась, спасибо!» and «Не стоит благодарности» are left alone. The AI
answers the question as it would in Direct, a short public reply under the comment («Ответили вам в Директ»)
tells the person where to look, and anything further is the usual dialogue. The business's own comments — the
pointer Joop posts, the owner answering under a post — never come back as questions (joop/web/app.py).
Off by default (`Business.ig_comments`); needs the «comments» webhook field and the instagram_manage_comments
permission in the Meta app (docs/channels.md). Manychat charges from $39 a month for the same trigger.
"""

from __future__ import annotations

import re

from .models import Business

DEFAULT_KEYWORDS = "цена, прайс, сколько, запись, записаться, запиши, свободно, окно, канча, баасы, жазыл"
DEFAULT_PUBLIC_REPLY = "Ответили вам в Директ"
_CLOSING = re.compile(r"^\W*(спасибо|благодарю|рахмат|записал)", re.I)  # «Спасибо, запись прошла отлично», «Записалась!»


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
    if "?" in t:
        return True
    if _CLOSING.match(t):
        return False
    return any(re.search(r"(?<!\w)" + re.escape(k), t) for k in keywords(business))


def own(business: Business, text: str, user_name: str) -> bool:
    """The business's own comment: the pointer Joop posted, or anything from the business's own username."""
    if text.strip() and text.strip() == business.ig_comment_public_reply.strip():
        return True
    return bool(business.ig_username) and user_name.strip().casefold() == business.ig_username.strip().casefold()
