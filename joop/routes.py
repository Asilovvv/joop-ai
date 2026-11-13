"""Prices by route (cargo and moving): the code finds the route in the price list, the model only repeats it.

A pack switches it on with ``features: [route_price]``. A price list line names its route as «Бишкек — Ош, ...».
When the customer's recent messages name two places, the prompt gets the matching lines (either direction), so
«из Джалал-Абада в Бишкек» finds «Бишкек — Джалал-Абад» whatever the spelling. A route that is not in the
price list is said to be missing, so the model asks the manager instead of guessing a price from the distance.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from .models import Conversation, Message, Service

LOOK_BACK = 6
# One place = its spellings (Russian, Kyrgyz, Latin, short forms). Word stems: «Оша», «Ошке», «в Нарын».
PLACES: dict[str, tuple[str, ...]] = {
    "Бишкек": ("бишкек", "bishkek", "фрунзе"),
    "Ош": ("ош", "osh"),
    "Джалал-Абад": ("джалал-абад", "жалал-абад", "джалалабад", "жалалабад", "jalal-abad"),
    "Каракол": ("каракол", "karakol"),
    "Нарын": ("нарын", "naryn"),
    "Талас": ("талас", "talas"),
    "Баткен": ("баткен", "batken"),
    "Токмок": ("токмок", "токмак", "tokmok"),
    "Кара-Балта": ("кара-балта", "карабалта", "kara-balta"),
    "Чолпон-Ата": ("чолпон-ата", "чолпоната", "cholpon-ata"),
    "Балыкчы": ("балыкчы", "рыбачье", "balykchy"),
    "Кант": ("кант", "kant"),
    "Узген": ("узген", "өзгөн", "uzgen"),
    "Алматы": ("алматы", "алма-ата", "almaty"),
    "Ташкент": ("ташкент", "tashkent"),
}
# A stem must start a word and may take a case ending: «Оша», «Ошко», «Бишкекке», «Нарынга».
_ENDINGS = r"(?:а|е|у|ом|ке|ка|ко|га|го|ге|ки|ку|та|те|тан|тен|дан|ден|нан|нен|ден|ге|ка|кө)?"


def _pattern(spellings: tuple[str, ...]) -> re.Pattern:
    stems = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.compile(rf"(?<![\wё-])(?:{stems}){_ENDINGS}(?![\wё])", re.IGNORECASE)


_PATTERNS = {place: _pattern(spellings) for place, spellings in PLACES.items()}


def places_in(text: str) -> list[str]:
    """Places named in the text, in the order they appear."""
    found = []
    for place, pattern in _PATTERNS.items():
        m = pattern.search(text or "")
        if m:
            found.append((m.start(), place))
    return [p for _, p in sorted(found)]


def route_of(name: str) -> frozenset[str] | None:
    """The two places of a price list line named «A — B ...», or None for a line without a route."""
    head = re.split(r"[,(]", name or "", maxsplit=1)[0]
    ends = re.split(r"\s*[—–-]{1,2}\s+|\s+[—–-]{1,2}\s*", head)
    if len(ends) != 2:
        return None
    a, b = (places_in(e) for e in ends)
    if len(a) == 1 and len(b) == 1 and a[0] != b[0]:
        return frozenset((a[0], b[0]))
    return None


def prompt_hint(session: Session, conv: Conversation, services: list[Service], text: str) -> str:
    routed = [(s, route_of(s.name)) for s in services]
    routed = [(s, r) for s, r in routed if r]
    if not routed:
        return ""
    texts = [text]
    if conv.id is not None:
        texts += list(session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer")
                                   .order_by(Message.id.desc()).limit(LOOK_BACK)).all())
    named: list[str] = []
    for t in texts:  # newest first: the latest message that names two places decides
        places = places_in(t)
        if len(places) >= 2:
            named = places[:2]
            break
    if not named:
        return ""
    want = frozenset(named)
    matches = [s for s, r in routed if r == want]
    route = f"{named[0]} — {named[1]}"
    if not matches:
        return (f"\nМаршрута {route} нет в прайсе (проверено системой). Цену не называй и по расстоянию не считай: "
                "собери данные для заявки, менеджер рассчитает.")
    lines = ["", f"Маршрут {route} найден в прайсе (проверено системой):"]
    lines += [f"- {s.name}: {s.price}" + (f" ({s.note})" if s.note else "") for s in matches]
    lines.append("Называй только эти цены; если груз не подходит под строку прайса, окончательную цену подтверждает менеджер.")
    return "\n".join(lines)
