"""Ready answers staff send from a dialogue in one tap («Готовые ответы»).

Chat2Desk, Wazzup and Bitrix24 open lines all have templates: an administrator answers the same ten questions all
day, so the panel keeps the answers and fills in the customer's name, the business's name, address and phone.
The text goes into the reply box first; nothing is sent until the person presses «Отправить клиенту».
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import Business, Conversation, QuickReply

MAX_REPLIES = 50
MAX_TITLE = 60
MAX_TEXT = 1000
FIELDS = ("{имя}", "{компания}", "{адрес}", "{телефон}")
STARTERS = [
    ("Перезвоним", "{имя}, спасибо! Администратор перезвонит вам в ближайшие 15 минут."),
    ("Адрес", "{имя}, мы находимся по адресу: {адрес}. Будем ждать вас!"),
    ("Время занято", "{имя}, на это время, к сожалению, всё занято. Подобрать ближайшее свободное?"),
    ("Спасибо за визит", "{имя}, спасибо, что были у нас! Будем рады видеть вас снова — {компания}."),
]


def listing(session: Session, business: Business) -> list[QuickReply]:
    return session.exec(select(QuickReply).where(QuickReply.business_id == business.id).order_by(QuickReply.title)).all()


def fill(text: str, business: Business, conv: Conversation | None = None) -> str:
    """The template with the fields filled; a field with nothing to put in goes away cleanly («, » and all)."""
    name = (conv.customer_name or conv.display_name).strip() if conv else ""
    values = {"{имя}": name, "{компания}": business.name, "{адрес}": business.address, "{телефон}": business.phone}
    out = text
    for key, value in values.items():
        if value:
            out = out.replace(key, value)
        else:
            out = out.replace(key + ", ", "").replace(", " + key, "").replace(key, "")
    out = out.strip()
    return out[:1].upper() + out[1:] if out else out


def add(session: Session, business: Business, title: str, text: str) -> str:
    """"" when saved, else why not."""
    title, text = " ".join(title.split())[:MAX_TITLE], text.strip()[:MAX_TEXT]
    if not title or not text:
        return "Нужны название и текст ответа."
    if len(listing(session, business)) >= MAX_REPLIES:
        return f"Не больше {MAX_REPLIES} готовых ответов."
    session.add(QuickReply(business_id=business.id, title=title, text=text))
    return ""


def add_starters(session: Session, business: Business) -> int:
    have = {r.title for r in listing(session, business)}
    new = [(t, x) for t, x in STARTERS if t not in have]
    for title, text in new:
        session.add(QuickReply(business_id=business.id, title=title, text=text))
    return len(new)
