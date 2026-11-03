"""The free plan: a solo master gets the AI for nothing, and the AI signs its replies with Joop.

The strategy's "the product carries its own distribution" move (docs: «Joop AI — стратегия с нуля»): a master who
works alone would not pay for an administrator, but her customers see the AI answer at 23:00 and ask where it
came from. So the plan is free for one master, never expires, and the AI adds one line with Joop's name and
address to the first reply in each conversation and to every reply that books a visit — the two moments a
customer reads to the end. A second master needs the paid plan; paying moves the business to it, and the
signature goes away. The line is added by code after the model's reply, so the prompt is unchanged.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import Staff, Subscription

FREE, PRO = "free", "pro"
MAX_STAFF = 1
CHANNELS = ("whatsapp", "instagram", "telegram")  # the web chat page already carries Joop's name in its header


def is_free(sub: Subscription | None) -> bool:
    return sub is not None and sub.plan == FREE


def active_staff(session: Session, business_id: int) -> list[Staff]:
    return list(session.exec(select(Staff).where(Staff.business_id == business_id, Staff.active == True)).all())  # noqa: E712


def eligible(session: Session, business_id: int) -> bool:
    """One master at most: the plan is for someone who works alone."""
    return len(active_staff(session, business_id)) <= MAX_STAFF


def switch(sub: Subscription) -> None:
    """To the free plan. The owner's cancellation, if any, is over: there is nothing to cancel."""
    sub.plan = FREE
    sub.cancelled_at, sub.cancel_reason = None, ""


def signature(base_url: str, kyrgyz: bool) -> str:
    line = "— Joop AI жооп берет, бизнес үчүн ИИ-администратор" if kyrgyz else "— отвечает Joop AI, ИИ-администратор для бизнеса"
    return f"\n\n{line} · {base_url}" if base_url else f"\n\n{line}"


def with_signature(reply: str, base_url: str, kyrgyz: bool) -> str:
    return reply.rstrip() + signature(base_url, kyrgyz)


TOO_MANY = "На бесплатном тарифе один мастер. Чтобы добавить второго, перейдите на платный тариф в разделе «Оплата»."
