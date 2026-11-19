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
    "чейин", "менен", "алыспы", "жакынбы",
}

RU_MESSAGE_MARKERS = {
    "сколько", "стоит", "можно", "хочу", "запишите", "записаться", "меня", "есть", "как", "где",
    "когда", "вы", "ваш", "ваша", "пожалуйста", "цена", "здравствуйте", "у", "в", "на", "и", "не",
    "это", "мне", "завтра", "работаете", "какие", "сделать",
}

_WORD = re.compile(r"[а-яёңөү]+")


def plural(n: int, one: str, few: str, many: str) -> str:
    """The Russian form after a number: 1 диалог, 2 диалога, 5 диалогов, 11 диалогов, 21 диалог."""
    n = abs(int(n or 0))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


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


def chat_is_kyrgyz(texts: list[str]) -> bool:
    """The chat's language from the customer's messages, newest first: the newest one with any Kyrgyz or Russian
    words decides. «Асель, 0555 112 233» after «көйнөктүн M өлчөмүн алайын» says nothing, so the chat stays Kyrgyz."""
    for text in texts:
        words = _words(text or "")
        ky = sum(1 for w in words if w in KY_MESSAGE_MARKERS or re.search("[ңөү]", w))
        ru = sum(1 for w in words if w in RU_MESSAGE_MARKERS)
        if ky != ru:
            return ky > ru
    return False


# A reply that claims something was booked, recorded or accepted.
_CLAIMS = re.compile(
    r"вы записаны|записал[аи]? (?:вас|ваш\w*)|запись (?:принята|оформлена|подтвержден\w*|создана)|"
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
_DIGIT_GAP = re.compile(r"(?<=\d)[ \u00a0\u202f](?=\d)")  # «1 500», «0555 123 456»: one number
_TIME = re.compile(r"(?<![\d.:])(\d{1,2}):(\d{2})(?![\d:])")
_DATE = re.compile(r"(?<![\d.:])(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?![\d.:])")
_NUMBER = re.compile(r"\d+")


def numbers(text: str) -> list[str]:
    """Every time, date and other number a reply names, as the customer would act on it: «09:00» and «9:00» are one
    time, «1 500» and «1500» one sum, «05.11» a date — another than «11.05», though the digits are the same."""
    text = _DIGIT_GAP.sub("", text)
    found = [f"t{int(h)}:{m}" for h, m in _TIME.findall(text)]
    text = _TIME.sub(" ", text)
    found += [f"d{int(d)}.{int(m)}" + (f".{int(y) % 100}" if y else "") for d, m, y in _DATE.findall(text)]
    found += [n.lstrip("0") or "0" for n in _NUMBER.findall(_DATE.sub(" ", text))]
    return sorted(found)


def _unmatched(draft: str, other: str) -> tuple[list[str], list[str]]:
    """What only the draft names and what only the other text names. A whole hour said the Kyrgyz way («саат 12де»)
    is the draft's «12:00», not a new number."""
    missing, extra = numbers(draft), []
    for n in numbers(other):
        if n in missing:
            missing.remove(n)
        elif f"t{n}:00" in missing:
            missing.remove(f"t{n}:00")
        else:
            extra.append(n)
    return missing, extra


def adds_no_numbers(draft: str, edited: str) -> bool:
    """An edit that only removes sentences may drop numbers with them, never add or change one."""
    return not _unmatched(draft, edited)[1]


def same_numbers(draft: str, rewritten: str) -> bool:
    """A rewrite in another language must keep every time, date, sum and phone of the draft and add none: many of them
    were written by the code (free times, the minimum order, a prescription, a deadline), not by the model."""
    missing, extra = _unmatched(draft, rewritten)
    return not missing and not extra


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


_CLOSER = re.compile(r"^\W*(спасибо|благодарю|рахмат|ок|окей|хорошо|понятно|ясно|ладно|пока|до свидания|жакшы|болду|👍)(?!\w)", re.I)
_ASKING = re.compile(r"запи[сш]|можно|хочу|хотим|нужн|надо|давайте|перенес|отмен|жазы|болобу|керек|сколько|канча|адрес|где", re.I)


def closing(text: str) -> bool:
    """The customer closing the chat — «Спасибо!», «Ок, понятно», «Хорошо, до встречи».

    Not «Ок, а сколько стоит?», «Спасибо, а на завтра можно записаться?», «Хорошо, запишите меня на 10:00»: a
    question mark, a number or a request word after the polite opener means they still want something.
    """
    t = (text or "").strip()
    return 0 < len(t) <= 40 and "?" not in t and not re.search(r"\d", t) and not _ASKING.search(t) and bool(_CLOSER.match(t))
