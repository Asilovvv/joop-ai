"""Does a customer's free text name a catalog item? Shared by «напишем, когда появится» (joop/restock.py) and the
prescription check of order comments (joop/prescription.py).

An item is named by its key word: the first word of its name (Russian or Kyrgyz) that is not a generic form word
(«Капли», «Раствор», «Крем») or a preposition. A customer's word matches it when it starts with the key's stem —
the key without its last two letters, never shorter than four (a key of four letters or less must be there whole) —
and is at most two letters longer than the key (one for keys under seven letters), the room endings need. So «маска», «маски»
match «Маски медицинские», while «маскара», «пара» (Пара носков vs «парацетамол»), «предварительно»
(Преднизолон) and «трамвая» (Трамадол) do not.
"""

from __future__ import annotations

import re

from .models import Service

GENERIC = {"капли", "раствор", "таблетки", "таблетка", "мазь", "крем", "сироп", "спрей", "гель", "порошок", "капсулы",
           "суспензия", "свечи", "набор", "тамчы", "эритме", "май"}  # form words that name no particular product
STOP = {"для", "от", "на", "по", "из", "под", "без", "с", "и", "в", "үчүн"}
_WORD = re.compile(r"[а-яёөүңa-z]+(?:-[а-яёөүңa-z]+)?")


def key_word(name: str) -> str:
    head = re.split(r"[,(]", (name or "").lower(), maxsplit=1)[0]
    words = [w for w in _WORD.findall(head) if w not in STOP and len(w) >= 3]
    useful = [w for w in words if w not in GENERIC]
    return (useful or words or [""])[0]


def _matches(key: str, word: str) -> bool:
    if len(key) <= 4:
        return word == key or (word.startswith(key) and len(word) - len(key) <= 2)
    stem = key[:max(4, len(key) - 2)]
    return word.startswith(stem) and len(word) <= len(key) + (2 if len(key) >= 7 else 1)  # «маскара» is not «маски»


def names(text: str, item: Service) -> bool:
    words = _WORD.findall((text or "").lower())
    keys = {k for k in (key_word(item.name), key_word(item.name_ky or "")) if k}
    return any(_matches(k, w) for k in keys for w in words)
