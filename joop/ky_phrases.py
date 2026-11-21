"""Every fixed Kyrgyz phrase in the product, for a native speaker to check (python -m joop ky-phrases, /owner/kyrgyz).

The model writes most Kyrgyz answers, but confirmations, reminders, buttons, the web chat and the booking page use
fixed phrases written without a native speaker and marked «проверить носителю». This finds them in the code itself,
so the list never goes stale. A string is Kyrgyz when the code says so or when it reads as Kyrgyz:

- it sits under a "ky" key at any depth ({"ky": {"title": …}}) or in a name with KY in it (BOOKED_KY, WEEKDAYS_KY_FULL);
- it is in the Kyrgyz branch of the code: `if kyrgyz: …`, `x if lang == "ky" else y`;
- it holds a letter Russian lacks (ң, ө, ү) or two common Kyrgyz words: most Kyrgyz sentences have no such letter.

Its Russian twin is shown when the code pairs them: the "ru" entry beside it, the same name with _RU or without _KY,
the other branch of the `if`. Left out: instructions to the model, the word lists that tell the language, test
dialogues (niches/*/cases.yaml) and the niches' fictional examples (demo.yaml)."""

from __future__ import annotations

import ast
import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .lang import KY_MESSAGE_MARKERS, RU_MESSAGE_MARKERS

ROOT = Path(__file__).resolve().parent
CYRILLIC = re.compile(r"[а-яёңөү]", re.I)
KY_LETTERS = re.compile(r"[ңөү]", re.I)
_WORD = re.compile(r"[а-яёңөү]+")
# Kyrgyz words that are Russian words too («же», «бар», «дары», «качан» the cabbage): no evidence of Kyrgyz
ALSO_RUSSIAN = {"же", "бар", "болот", "мага", "дары", "качан", "салам"}
KY_WORDS = (KY_MESSAGE_MARKERS | {
    "макул", "убакыт", "бош", "азыр", "азырынча", "кайра", "эмес", "калат", "койдум", "алдым", "тандаңыз", "бериңиз",
    "жазылдыңыз", "буйрутма", "кызмат", "ушул", "ошол", "бир", "деп", "эле", "гана", "кийин", "мурун", "жерге", "жерде",
    "кайсы", "биз", "бизге", "бизде", "бизди", "болсо", "болду", "боюнча", "аркылуу", "туура", "даяр", "алып", "берем",
    "беребиз", "жазам", "жазабыз"}) - ALSO_RUSSIAN
# Russian words Kyrgyz does not use: a line with more of these than Kyrgyz ones is a Russian keyword list
RU_WORDS = (RU_MESSAGE_MARKERS | {"для", "что", "если", "или", "чтобы", "нет", "уже", "только", "запись"}) - {"у", "в", "на", "и"}
SENTENCE_START = re.compile(r"(?:^|[.!?…«(\n])\s*$")
KY_NAME = re.compile(r"(?:^|_)ky(?:_|$)", re.I)  # BOOKED_KY, WEEKDAYS_KY_FULL, text_ky
KY_FLAGS = {"kyrgyz", "ky", "is_kyrgyz", "is_ky", "in_kyrgyz"}  # `if kyrgyz:`
KY_CALLS = {"is_kyrgyz_message", "chat_is_kyrgyz", "_kyrgyz"}  # `if is_kyrgyz_message(text):`
REGEX = re.compile(r"\[[^\]]*-[^\]]*\]|\\[bdswBDSW]|^\^|\(\?")
# instructions to the model (checked by the model evaluation, never shown as they are), the word lists that tell the
# language, and this file
SKIP_FILES = {"ky_phrases.py", "prompt.py", "kyrgyz.py", "lang.py"}
SKIP_DIRS = {"__pycache__", "migrations"}
JOINER = " · "  # between the words of a list (weekdays, the words that stop a broadcast)

# Where the customer meets the phrase, for the speaker: the first match wins; anything else is «Сообщения клиентам».
SECTIONS = (
    ("joop/web/booking_page.py", "Страница записи без переписки"),
    ("joop/page_booking.py", "Страница записи без переписки"),
    ("joop/web/menu.py", "Онлайн-страница: меню и прайс"),
    ("joop/web/webchat.py", "Чат на сайте"),
    ("joop/web/templates/webchat.html", "Чат на сайте"),
    ("joop/web/templates/site_", "Сайт Joop AI"),
    ("joop/web/templates/owner_case.html", "Сообщения основателя компаниям"),
    ("joop/web/templates/", "Наклейка, карточка на стойку, примеры в панели"),
    ("joop/web/", "Панель и консоль"),
    ("joop/confirm", "Подтверждение записи и напоминание"),
    ("joop/scheduler.py", "Подтверждение записи и напоминание"),
    ("joop/broadcasts.py", "Рассылки и отписка"),
    ("joop/deposits.py", "Предоплата"),
    ("joop/holds.py", "Предоплата"),
    ("joop/followups.py", "Отзыв и приглашение прийти снова"),
    ("joop/gaps.py", "Отзыв и приглашение прийти снова"),
    ("joop/reorders.py", "Заказы: повтор, статус, наличие"),
    ("joop/restock.py", "Заказы: повтор, статус, наличие"),
    ("joop/order_status.py", "Заказы: повтор, статус, наличие"),
    ("joop/jobs.py", "Заказы: повтор, статус, наличие"),
    ("joop/pitch.py", "Сообщения основателя компаниям"),
    ("joop/case.py", "Сообщения основателя компаниям"),
    ("joop/agent/", "Ответы ИИ: готовые фразы"),
    ("mobile/", "Приложение для телефона"),
)
OTHER_SECTION = "Сообщения клиентам"


@dataclass(frozen=True)
class Phrase:
    where: str  # file:line
    ky: str
    ru: str = ""

    @property
    def section(self) -> str:
        return next((label for prefix, label in SECTIONS if self.where.startswith(prefix)), OTHER_SECTION)


def _kyrgyz_line(line: str) -> bool:
    kyrgyz: set[str] = set()
    for m in re.finditer(r"[а-яёңөү]+", line, re.I):
        word = m.group(0)
        if word.lower() in KY_WORDS:
            kyrgyz.add(word.lower())
        elif KY_LETTERS.search(word) and (word.islower() or SENTENCE_START.search(line[:m.start()])):
            kyrgyz.add(word.lower())  # «мастер Нургүл» is a Russian line with a Kyrgyz name
    words = {w.lower() for w in _WORD.findall(line.lower())}
    russian = words & RU_WORDS
    by_letter = any(KY_LETTERS.search(w) for w in kyrgyz) and len(line.split()) >= 2
    return (by_letter or len(kyrgyz) >= 2) and len(kyrgyz) >= len(russian)


def looks_kyrgyz(text: str) -> bool:
    """Some line of the text has a word with a Kyrgyz letter (and is not that one word: an entry of a word list), or
    two common Kyrgyz words, and no more Russian words than Kyrgyz ones."""
    return any(_kyrgyz_line(line) for line in text.split("\n"))


# --- Python ------------------------------------------------------------------------------------------------------


def _text(node: ast.AST | None) -> str | None:
    """A string literal, or an f-string with its placeholders as {…}."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("{" + (ast.unparse(v.value) if isinstance(v, ast.FormattedValue) else "…") + "}")
        return "".join(parts)
    return None


def _words(node: ast.AST | None) -> list[str] | None:
    """The strings of a tuple, list or set of nothing but strings."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and node.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    return None


def _word_list(node: ast.AST | None) -> bool:
    """Weekdays, the words that stop a broadcast, «да» in ten spellings: short entries, shown as one line."""
    words = _words(node)
    return bool(words) and all(len(w.split()) <= 2 for w in words)


def _shown(node: ast.AST) -> str:
    return JOINER.join(_words(node) or []) if _word_list(node) else (_text(node) or "")


def _is_phrase(text: str | None) -> bool:
    return bool(text and text.strip() and CYRILLIC.search(text) and not REGEX.search(text))


def _literals(nodes: Iterable[ast.AST]) -> list[ast.AST]:
    """The texts inside these nodes, in the order they are written. Docstrings are not texts."""
    out: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            return
        if _text(node) is not None:
            if _is_phrase(_text(node)):
                out.append(node)
            return
        if isinstance(node, ast.Dict):  # keys are what the code looks up, not what the customer reads
            for value in node.values:
                visit(value)
            return
        words = _words(node)
        if words and len(words) >= 3 and all(len(w.split()) <= 3 for w in words):
            return  # a keyword list: «самовывоз», «заберу», «өзү алып кетет»
        for child in ast.iter_child_nodes(node):
            visit(child)

    for node in nodes:
        visit(node)
    return sorted(out, key=lambda n: (n.lineno, n.col_offset))


def _leaves(node: ast.AST | None, path: tuple = ()) -> Iterator[tuple[tuple, ast.AST]]:
    """The texts under a value with the way to each: {"title": "…", "days": (…)} -> ("title",), ("days",)."""
    if node is None:
        return
    if _text(node) is not None or _word_list(node):
        if _is_phrase(_shown(node)):
            yield path, node
    elif isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant):
                yield from _leaves(value, path + (key.value,))
    elif _words(node):  # a list of sentences: each is its own phrase
        for i, element in enumerate(node.elts):
            yield from _leaves(element, path + (i,))
    else:  # "a" + name + "b", a conditional, a call: its texts by position
        for i, leaf in enumerate(_literals([node])):
            yield path + (i,), leaf


def _names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for t in target.elts for n in _names(t)]
    return []


def _assigned(tree: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    """name, value of every plain assignment: X = "…", and each side of A, B = "…", "…"."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        for target in targets:
            names = _names(target)
            if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)) \
                    and len(value.elts) == len(names):
                yield from zip(names, value.elts)
            elif len(names) == 1:
                yield names[0], value


def _kyrgyz_test(test: ast.AST) -> bool | None:
    """True: the test holds for Kyrgyz; False: for everything but Kyrgyz; None: it is not about the language."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _kyrgyz_test(test.operand)
        return None if inner is None else not inner
    if isinstance(test, ast.Name):
        return True if test.id in KY_FLAGS else None
    if isinstance(test, ast.Attribute):
        return True if test.attr in KY_FLAGS else None
    if isinstance(test, ast.Call):
        name = test.func.id if isinstance(test.func, ast.Name) else getattr(test.func, "attr", "")
        return True if name in KY_CALLS else None
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.comparators[0], ast.Constant) \
            and test.comparators[0].value == "ky":
        return True if isinstance(test.ops[0], ast.Eq) else False if isinstance(test.ops[0], ast.NotEq) else None
    return None


def _language_branches(tree: ast.AST) -> Iterator[tuple[list[ast.AST], list[ast.AST]]]:
    """(the Kyrgyz side, the other side) of every `if` on the language.

    `if kyrgyz: return …` with no else is followed by the Russian text: the next statements are the other side."""
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp):
            kyrgyz = _kyrgyz_test(node.test)
            if kyrgyz is not None:
                yield ([node.body], [node.orelse]) if kyrgyz else ([node.orelse], [node.body])
        for block in (getattr(node, name, None) for name in ("body", "orelse", "finalbody")):
            if not isinstance(block, list):
                continue
            for i, stmt in enumerate(block):
                if not isinstance(stmt, ast.If):
                    continue
                kyrgyz = _kyrgyz_test(stmt.test)
                if kyrgyz is None:
                    continue
                leaves = isinstance(stmt.body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))
                rest = block[i + 1:] if leaves and not stmt.orelse and len(block) - i - 1 <= 6 else []
                if kyrgyz:
                    yield stmt.body, stmt.orelse or rest
                elif stmt.orelse:
                    yield stmt.orelse, stmt.body


def _twin_names(name: str) -> list[str]:
    """Where the Russian text of BOOKED_KY may live: BOOKED_RU, BOOKED."""
    russian = KY_NAME.sub(lambda m: m.group(0).replace("KY", "RU").replace("ky", "ru"), name)
    bare = re.sub(r"_ky(?=_|$)|^ky_", "", name, flags=re.I)
    return [n for n in (russian, bare) if n and n != name]


def _from_python(path: Path, base: Path) -> list[Phrase]:
    rel = path.relative_to(base).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[int, tuple[ast.AST, str]] = {}  # by node: the text and its Russian twin

    def add(node: ast.AST, ru: str | None = "") -> None:
        if not _is_phrase(_shown(node)):
            return
        known = found.get(id(node))
        if known is None or (ru and not known[1]):
            found[id(node)] = (node, ru or "")

    def add_paired(ky: ast.AST | None, ru: ast.AST | None) -> None:
        twins = {way: _shown(leaf) for way, leaf in _leaves(ru)}
        for way, leaf in _leaves(ky):
            add(leaf, twins.get(way))

    constants = dict(_assigned(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
            if "ky" in keys:
                add_paired(keys["ky"], keys.get("ru"))
    for name, value in _assigned(tree):
        if KY_NAME.search(name):
            add_paired(value, next((constants[n] for n in _twin_names(name) if n in constants), None))
    for ky_side, other_side in _language_branches(tree):
        ky, other = _literals(ky_side), _literals(other_side)
        for i, node in enumerate(ky):
            add(node, _text(other[i]) if len(other) == len(ky) else "")
    for node in _literals([tree]):
        if looks_kyrgyz(_text(node) or ""):
            add(node)
    return [Phrase(f"{rel}:{node.lineno}", *_split_languages(_shown(node), ru)) for node, ru in found.values()]


def _split_languages(ky: str, ru: str) -> tuple[str, str]:
    """One text with a Kyrgyz line and a Russian line (the reply to a photo, to a model failure): each to its column."""
    lines = [line for line in ky.split("\n") if line.strip()]
    if ru or len(lines) < 2:
        return ky, ru
    kyrgyz = [line for line in lines if looks_kyrgyz(line)]
    russian = [line for line in lines if not looks_kyrgyz(line) and CYRILLIC.search(line)]
    return ("\n".join(kyrgyz), "\n".join(russian)) if kyrgyz and russian else (ky, ru)


# --- templates ---------------------------------------------------------------------------------------------------

TAG = re.compile(r"<[^>]+>|\{[{%#].*?[}%#]\}")
QUOTED = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""")
JS_LANGUAGE = re.compile(r"\b(ru|ky)\s*:\s*\{")
JS_PAIR = re.compile(r"""(\w+)\s*:\s*(['"])((?:\\.|(?!\2).)*)\2""")
KY_ELEMENT = re.compile(r"""<(\w+)[^>]*\bclass=["'](?:[^"']*\s)?ky(?:\s[^"']*)?["'][^>]*>(.*?)</\1>""", re.S)
# {{ 'по-русски' if lang == 'ru' else 'кыргызча' }} and the same turned round
JINJA_BY_RU = re.compile(r"""(['"])((?:(?!\1).)*)\1\s+if\s+[\w.]+\s*==\s*['"]ru['"]\s+else\s+(['"])((?:(?!\3).)*)\3""")
JINJA_BY_KY = re.compile(r"""(['"])((?:(?!\1).)*)\1\s+if\s+[\w.]+\s*==\s*['"]ky['"]\s+else\s+(['"])((?:(?!\3).)*)\3""")


def _from_template(path: Path, base: Path) -> list[Phrase]:
    rel = path.relative_to(base).as_posix()
    source = path.read_text(encoding="utf-8")
    line_of = lambda position: source.count("\n", 0, position) + 1  # noqa: E731
    out: list[Phrase] = []
    taken: set[int] = set()

    # the page's own texts by language in its script: ru: {send: '…'}, ky: {send: '…'}
    tables: dict[str, list[tuple[str, str, int]]] = {"ru": [], "ky": []}
    for m in JS_LANGUAGE.finditer(source):
        end, depth = m.end(), 1
        while end < len(source) and depth:
            depth += {"{": 1, "}": -1}.get(source[end], 0)
            end += 1
        tables[m.group(1)] += [(p.group(1), p.group(3), line_of(m.end() + p.start(3)))
                               for p in JS_PAIR.finditer(source[m.end():end])]
    russian = {key: text for key, text, _ in tables["ru"]}
    for key, text, line in tables["ky"]:
        if _is_phrase(text):
            out.append(Phrase(f"{rel}:{line}", text, russian.get(key, "")))
            taken.add(line)
    # an element marked as the Kyrgyz line of a printed card: <p class="ky">…</p>
    for m in KY_ELEMENT.finditer(source):
        text = " ".join(TAG.sub(" ", m.group(2)).split())
        if _is_phrase(text):
            out.append(Phrase(f"{rel}:{line_of(m.start(2))}", text))
            taken.add(line_of(m.start(2)))
    # anything else that reads as Kyrgyz: an example dialogue on the site, a placeholder, a label chosen by language
    for number, line in enumerate(source.splitlines(), 1):
        if number in taken or not looks_kyrgyz(line):
            continue
        twins = {m.group(4): m.group(2) for m in JINJA_BY_RU.finditer(line)}
        twins.update({m.group(2): m.group(4) for m in JINJA_BY_KY.finditer(line)})
        quoted = [q for q in dict.fromkeys(m.group(2).strip() for m in QUOTED.finditer(line)) if q in twins or looks_kyrgyz(q)]
        plain = [c for c in dict.fromkeys(" ".join(chunk.split()) for chunk in TAG.split(line))
                 if looks_kyrgyz(c) and not any(q in c for q in quoted)]  # not the script line a quoted text sits in
        for piece in quoted + plain:
            out.append(Phrase(f"{rel}:{number}", piece, twins.get(piece, "")))
    return out


# --- the list ----------------------------------------------------------------------------------------------------


def collect(root: Path = ROOT) -> list[Phrase]:
    base = root.parent
    phrases: list[Phrase] = []
    for path in sorted(root.rglob("*.py")):
        if path.name not in SKIP_FILES and not SKIP_DIRS & set(path.parts):
            phrases.extend(_from_python(path, base))
    for path in sorted((root / "web" / "templates").glob("*.html")):
        phrases.extend(_from_template(path, base))
    if root == ROOT:  # the mobile app's texts, from their snapshot (joop/app_strings.py)
        from .app_strings import WHERE, snapshot

        phrases.extend(Phrase(f"{WHERE}:{row['line']}", row["ky"], row["ru"]) for row in snapshot())
    order = {label: i for i, label in enumerate(dict.fromkeys([label for _, label in SECTIONS] + [OTHER_SECTION]))}
    lines: dict[tuple[str, str, str], list[int]] = {}  # the same text twice in a file is one phrase: «file:113,121»
    for p in phrases:
        name, _, line = p.where.rpartition(":")
        lines.setdefault((name, p.ky, p.ru), []).append(int(line))
    unique = [Phrase(f"{name}:{','.join(map(str, sorted(set(at))))}", ky, ru) for (name, ky, ru), at in lines.items()]
    return sorted(unique, key=lambda p: (order[p.section], p.where.split(":")[0], int(re.split(r"[:,]", p.where)[1])))


def to_csv(phrases: list[Phrase]) -> str:
    """For the native speaker: where the customer meets it, Russian, Kyrgyz, and two empty columns to fill."""
    out = io.StringIO()
    out.write("﻿")  # Excel opens UTF-8 with Cyrillic correctly
    w = csv.writer(out)
    w.writerow(["№", "Раздел", "По-русски", "По-кыргызски", "Верно? (да/нет)", "Как правильно", "Где в коде"])
    for i, p in enumerate(phrases, 1):
        w.writerow([i, p.section, p.ru, p.ky, "", "", p.where])
    return out.getvalue()
