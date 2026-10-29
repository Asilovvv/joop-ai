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


# A reply that claims something was booked, recorded or accepted.
_CLAIMS = re.compile(
    r"вы записаны|записал[аи]? вас|запись (?:принята|оформлена|подтвержден\w*|создана)|"
    r"заявк\w* (?:принята|оформлена)|заказ (?:принят|оформлен|подтвержд\w*)|бронь (?:оформлена|подтвержден\w*)|"
    r"забронировал[аи]?|кабыл ал(?:ынды|дым|дык)|жазып (?:койдум|коюлду)|катталды|жазылдыңыз",
    re.IGNORECASE,
)


def claims_confirmation(text: str) -> bool:
    """Does the reply say a booking, request or order is already made?"""
    return bool(_CLAIMS.search(text or ""))


_SENTENCE = re.compile(r".+?(?:[.!?]+(?=\s|$)|$)\s*", re.S)


def drop_claim_sentences(text: str) -> str:
    """Last resort when the rewrite failed: remove the sentences that claim a booking was made.
    Returns "" when nothing useful (a question or other text) would be left."""
    kept = "".join(part for part in _SENTENCE.findall(text or "") if not claims_confirmation(part)).strip()
    return kept if len(kept) >= 15 else ""


# Latin letters that look like Cyrillic ones. The model sometimes puts one inside
# a Cyrillic word ("Бааsы", "алbаймын"); readers see a typo, search breaks.
_LATIN_TO_CYRILLIC = str.maketrans({
    "a": "а", "b": "б", "c": "с", "e": "е", "k": "к", "m": "м", "o": "о", "p": "р",
    "s": "с", "t": "т", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "K": "К", "M": "М", "O": "О", "P": "Р",
    "T": "Т", "X": "Х", "Y": "У",
})
_MIXED_WORD = re.compile(r"\b(?=\w*[А-Яа-яЁёҢңӨөҮү])(?=\w*[A-Za-z])\w+\b")


def fix_mixed_script(text: str) -> str:
    """Replace Latin look-alike letters inside words that are mostly Cyrillic.
    Pure Latin words (brand names, "QR") are left alone."""
    return _MIXED_WORD.sub(lambda m: m.group(0).translate(_LATIN_TO_CYRILLIC), text)


def use_kyrgyz_names(text: str, names: dict[str, str]) -> str:
    """Swap Russian service names left in a Kyrgyz reply for their Kyrgyz names
    from the profile (case-insensitive; keeps a capital first letter)."""
    for ru, ky in sorted(names.items(), key=lambda kv: -len(kv[0])):
        if not ru or not ky:
            continue

        def repl(m: re.Match, ky: str = ky) -> str:
            return ky[0].upper() + ky[1:] if m.group(0)[0].isupper() else ky[0].lower() + ky[1:]

        text = re.sub(re.escape(ru), repl, text, flags=re.IGNORECASE)
    return text
