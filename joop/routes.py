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
    "Алматы": ("алматы", "алма-ат", "almaty"),
    "Ташкент": ("ташкент", "tashkent"),
}
# A stem must start a word and may take a case ending: «Оша», «Ошко», «Бишкекке», «Нарынга», «Оштон», «Алма-Аты».
FROM_ENDINGS = ("тан", "тен", "тон", "төн", "дан", "ден", "дон", "дөн", "нан", "нен", "нон", "нөн")  # Kyrgyz «from»
TO_ENDINGS = ("ка", "ке", "ко", "кө", "га", "ге", "го", "гө", "а", "е", "о", "ө")  # Kyrgyz «to» (а/е after a vowel-final stem)
_ENDINGS = "(?:" + "|".join(sorted(set(FROM_ENDINGS + TO_ENDINGS + ("у", "ы", "ом", "ки", "ку", "та", "те", "ту", "ты")),
                                  key=len, reverse=True)) + ")?"
# «Ош базар», «Бишкек Парк»: a place inside a city, not the city.
_INSIDE = re.compile(r"\s+(?:базар\w*|рын(?:ок|ка|ке|ку)\b|парк\w*|молл\w*)", re.IGNORECASE)
_FROM_WORD = re.compile(r"(?:^|\s)(?:из|с|со|от)\s+$", re.IGNORECASE)
_TO_WORD = re.compile(r"(?:^|\s)(?:в|во|до|на)\s+$", re.IGNORECASE)


def _pattern(spellings: tuple[str, ...]) -> re.Pattern:
    stems = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.compile(rf"(?<![\wё])(?:{stems}){_ENDINGS}(?![\wё])", re.IGNORECASE)


_PATTERNS = {place: _pattern(spellings) for place, spellings in PLACES.items()}


def _mentions(text: str) -> list[tuple[int, str, str]]:
    """(position, place, "from" | "to" | "") for each city named in the text, in order; places inside a city skipped."""
    text = text or ""
    found = []
    for place, pattern in _PATTERNS.items():
        for m in pattern.finditer(text):
            if _INSIDE.match(text, m.end()):
                continue
            word, before = m.group(0).lower(), text[:m.start()]
            if _FROM_WORD.search(before):  # Russian: «из Оша», «с Каракола»
                role = "from"
            elif _TO_WORD.search(before):  # «в Ош», «до Нарына»; «в Бишкеке» is where the customer is, not where to
                role = "" if re.search(r"(?:в|во)\s+$", before, re.IGNORECASE) and word.endswith(("е", "у")) else "to"
            elif word.endswith(FROM_ENDINGS):  # Kyrgyz: «Оштон», «Бишкектен»
                role = "from"
            elif word.endswith(TO_ENDINGS[:8]):  # Kyrgyz: «Бишкекке», «Нарынга»
                role = "to"
            else:
                role = ""
            found.append((m.start(), place, role))
            break
    return sorted(found)


def places_in(text: str) -> list[str]:
    """Cities named in the text, in the order they appear."""
    return [place for _, place, _ in _mentions(text)]


def route_in(text: str) -> tuple[str, str] | None | bool:
    """The route the message asks about: (from, to) in the customer's order; None when it names fewer than two cities;
    False when it names more and does not say which is «from» and which is «to»."""
    found = _mentions(text)
    if len(found) < 2:
        return None
    if len(found) == 2:
        return found[0][1], found[1][1]
    start = [p for _, p, r in found if r == "from"]
    end = [p for _, p, r in found if r == "to"]
    if len(start) == 1 and len(end) == 1 and start != end:
        return start[0], end[0]
    return False


def route_of(name: str) -> frozenset[str] | None:
    """The two cities of a price list line named «A — B ...» (any dash, with or without spaces), else None."""
    head = re.split(r"[,(]", name or "", maxsplit=1)[0]
    places = places_in(head)
    if len(places) == 2 and re.search(r"[—–-]", head):
        return frozenset(places)
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
    named: tuple[str, str] | None = None
    for t in texts:  # newest first: the latest message that names two cities decides
        found = route_in(t)
        if found is False:
            return ("\nКлиент назвал больше двух городов (проверено системой). Уточни, откуда и куда везти; "
                    "цену пока не называй.")
        if found:
            named = found
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
