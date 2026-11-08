"""The free plan: a solo master gets the AI for nothing, and the AI signs its replies with Joop.

The strategy's "the product carries its own distribution" move (docs: «Joop AI — стратегия с нуля»): a master who
works alone would not pay for an administrator, but her customers see the AI answer at 23:00 and ask where it
came from. So the plan is free for one master, never expires, and the AI adds one line with Joop's name and
address to the first reply in each conversation and to every reply that books a visit — the two moments a
customer reads to the end. A second master needs the paid plan; paying moves the business to it, and the
signature goes away. The line is added by code after the model's reply, so the prompt is unchanged. Its link is
`/ai/<slug>`: every visit is counted per business (`SignatureClick`), a sign-up that follows is `signup-ai`, and the
founder console shows both — the only honest measure of whether the free plan brings customers (docs: tactics,
"powered-by loop"). The master sees her own count on the billing page.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import SignatureClick, Staff, Subscription

FREE, PRO = "free", "pro"
MAX_STAFF = 1
CHANNELS = ("whatsapp", "instagram", "telegram")  # the web chat page already carries Joop's name in its header


def is_free(sub: Subscription | None) -> bool:
    return sub is not None and sub.plan == FREE


def active_staff(session: Session, business_id: int) -> list[Staff]:
    """The business's real masters: the sign-up example (Айжан, Нургуль…) is not a second master."""
    from . import samples
    from .models import Business

    rows = list(session.exec(select(Staff).where(Staff.business_id == business_id, Staff.active == True)).all())  # noqa: E712
    business = session.get(Business, business_id)
    example = samples.example_staff_ids(session, business) if business is not None else set()
    return [r for r in rows if r.id not in example]


def eligible(session: Session, business_id: int) -> bool:
    """One master at most: the plan is for someone who works alone."""
    return len(active_staff(session, business_id)) <= MAX_STAFF


def switch(sub: Subscription) -> None:
    """To the free plan. The owner's cancellation, if any, is over: there is nothing to cancel."""
    sub.plan = FREE
    sub.cancelled_at, sub.cancel_reason = None, ""


def signature(base_url: str, kyrgyz: bool, slug: str = "") -> str:
    """One line with Joop's name and a link that says which business's AI the reader saw (counted in signature_link)."""
    line = "— Joop AI жооп берет, бизнес үчүн ИИ-администратор" if kyrgyz else "— отвечает Joop AI, ИИ-администратор для бизнеса"
    link = f"{base_url}/ai/{slug}" if base_url and slug else base_url
    return f"\n\n{line} · {link}" if link else f"\n\n{line}"


def with_signature(reply: str, base_url: str, kyrgyz: bool, slug: str = "") -> str:
    return reply.rstrip() + signature(base_url, kyrgyz, slug)


def clicks(session: Session, business_id: int, since) -> int:
    """How many people followed this business's signature to Joop's site since `since`: the master sees her own number."""
    from sqlalchemy import func

    return session.exec(select(func.count()).select_from(SignatureClick).where(
        SignatureClick.business_id == business_id, SignatureClick.created_at >= since)).one() or 0


TOO_MANY = "На бесплатном тарифе один мастер. Чтобы добавить второго, перейдите на платный тариф в разделе «Оплата»."
TOO_MANY_EXAMPLE = ("На бесплатном тарифе один мастер, а в примере их несколько. Удалите лишних в разделе «Мастера» — или"
                    " перейдите на платный тариф в разделе «Оплата».")


def breaks_plan(session: Session, business_id: int) -> bool:
    """On the free plan, a change (already flushed) leaves more than one real master: the AI would stop answering
    (billing.access_ok), so the change is refused instead."""
    from . import billing

    return is_free(billing.get_subscription(session, business_id)) and not eligible(session, business_id)
