"""Lightweight Kyrgyz/Russian language heuristics (no external models).

Used by the agent's language guard and by the evaluation. They are word-list
heuristics: good enough to catch a reply in the wrong language, not a general
language identifier.
"""

from __future__ import annotations

import re

# Common Kyrgyz words that do not occur in Russian. Capitalised names such as
# "Гүлнара" are not counted.
KY_REPLY_MARKERS = {
    "сиз", "сизге", "сиздин", "сизди", "жана", "үчүн", "менен", "болот", "керек", "бар", "жок",
    "жакында", "кабыл", "алынды", "жазылуу", "жазып", "жазыңыз", "эртең", "саат", "баасы", "турат",
    "дарыгер", "дарыгердин", "дароо", "чалыңыз", "атыңызды", "номериңизди", "убакытты", "кечиресиз",
    "кечириңиз", "ооба", "биздин", "бул", "же", "эгер", "жооп", "берет", "дагы", "суроо",
    "суроонуз", "суроолоруңуз", "сураңыз", "шаары", "көчөсү", "дарегибиз", "рахмат",
}

# Words typical of short Kyrgyz customer messages (questions, booking requests).
KY_MESSAGE_MARKERS = KY_REPLY_MARKERS | {
    "канча", "барбы", "кайда", "келет", "болобу", "жазылгым", "жазылсам", "атым", "тиш", "кандай",
    "качан", "мага", "мени", "менин", "саламатсызбы", "салам", "болот", "балама", "жазып", "коюңузчу",
    "керекпи", "иштейсиздер", "иштейсизби", "төлөсө", "төлөм", "дары", "ооруп", "ооруйт", "шишип",
    "кечээ", "абдан", "начар", "нааразымын", "нааразы", "жакшы", "эмне", "эмнеге", "кантип",
}

RU_MESSAGE_MARKERS = {
    "сколько", "стоит", "можно", "хочу", "запишите", "записаться", "меня", "есть", "как", "где",
    "когда", "вы", "ваш", "ваша", "пожалуйста", "цена", "здравствуйте", "у", "в", "на", "и", "не",
    "это", "мне", "завтра", "работаете", "какие", "сделать",
}

_WORD = re.compile(r"[а-яёңөү]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def looks_kyrgyz(text: str) -> bool:
    """Is this (reply) text in Kyrgyz? At least two common Kyrgyz words, or at
    least two lower-case words containing the letters ң, ө, ү."""
    words = set(_words(text))
    special = {w for w in re.findall(r"\b[а-яёңөү]+\b", text) if re.search("[ңөү]", w)}
    return len(words & KY_REPLY_MARKERS) >= 2 or len(special) >= 2


def is_kyrgyz_message(text: str) -> bool:
    """Did the customer write mostly in Kyrgyz? Short messages are scored by
    Kyrgyz versus Russian marker words; Kyrgyz letters count as Kyrgyz evidence."""
    words = _words(text)
    ky = sum(1 for w in words if w in KY_MESSAGE_MARKERS or re.search("[ңөү]", w))
    ru = sum(1 for w in words if w in RU_MESSAGE_MARKERS)
    return ky >= 1 and ky > ru
