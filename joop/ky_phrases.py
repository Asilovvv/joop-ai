"""Every fixed Kyrgyz phrase in the product, for a native speaker to check (python -m joop ky-phrases, /owner/kyrgyz).

The model writes most Kyrgyz answers, but confirmations, reminders, buttons, the web chat and the booking page use
fixed phrases written without a native speaker and marked «проверить носителю». This finds them in the code itself,
so the list never goes stale: a string is Kyrgyz when it holds a letter Russian lacks (ң, ө, ү), is the "ky" entry of
a dict, or is assigned to a name ending in _KY. Its Russian twin is shown when the code pairs them (the "ru" entry of
the same dict, the same name with _RU). Test dialogues (niches/*/cases.yaml) and the fictional demo are left out."""

from __future__ import annotations

import ast
import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KY_LETTERS = re.compile(r"[ңөүҢӨҮ]")
TEMPLATE_STRING = re.compile(r"""(['"])((?:(?!\1).)*[ңөүҢӨҮ](?:(?!\1).)*)\1""")
TAG = re.compile(r"<[^>]+>|\{[{%#].*?[}%#]\}")
# instructions to the model (checked by the model evaluation, never shown as they are) and this file
SKIP_FILES = {"ky_phrases.py", "prompt.py", "kyrgyz.py"}
REGEX = re.compile(r"\[[^\]]*-[^\]]*\]|\\[bdswBDSW]|^\^|\(\?")


@dataclass(frozen=True)
class Phrase:
    where: str  # file:line
    ky: str
    ru: str = ""


def _text(node: ast.AST) -> str | None:
    """A string literal, or an f-string with its placeholders shown as {…}."""
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


def _names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for t in target.elts for n in _names(t)]
    return []


def _from_python(path: Path) -> list[Phrase]:
    rel = path.relative_to(ROOT.parent).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[int, Phrase] = {}  # by node id: one phrase per literal
    constants: dict[str, str] = {}  # NAME -> text, for _RU twins

    def add(node: ast.AST, ru: str = "") -> None:
        text = _text(node)
        if text and text.strip() and not REGEX.search(text) and id(node) not in found:
            found[id(node)] = Phrase(f"{rel}:{node.lineno}", text, ru)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = _names(node.targets[0])
            values = node.value.elts if isinstance(node.value, ast.Tuple) and len(names) > 1 else [node.value]
            for name, value in zip(names, values):
                text = _text(value)
                if text is not None:
                    constants[name] = text
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
            ky = keys.get("ky")
            if ky is not None and _text(ky) is not None:
                ru = keys.get("ru")
                add(ky, (_text(ru) or "") if ru is not None else "")
        elif isinstance(node, ast.Assign):
            names = _names(node.targets[0])
            values = node.value.elts if isinstance(node.value, ast.Tuple) and len(names) > 1 else [node.value]
            for name, value in zip(names, values):
                if name.endswith("_KY") and _text(value) is not None:
                    add(value, constants.get(name[:-3] + "_RU", ""))
    for node in ast.walk(tree):
        text = _text(node)
        # found by its letters alone: a phrase, not one word of a word list (language detection, synonyms)
        if text and KY_LETTERS.search(text) and len(text.split()) >= 2:
            add(node)
    # a constant inside an f-string is reported with the f-string, not again on its own; docstrings are not phrases
    inner = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    inner |= {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr)}
    return [p for key, p in found.items() if key not in inner]


def _from_template(path: Path) -> list[Phrase]:
    rel = path.relative_to(ROOT.parent).as_posix()
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not KY_LETTERS.search(line):
            continue
        quoted = [m.group(2) for m in TEMPLATE_STRING.finditer(line)]
        pieces = quoted or [" ".join(TAG.sub(" ", line).split())]
        out.extend(Phrase(f"{rel}:{number}", piece.strip()) for piece in pieces if KY_LETTERS.search(piece))
    return out


def collect(root: Path = ROOT) -> list[Phrase]:
    phrases: list[Phrase] = []
    for path in sorted(root.rglob("*.py")):
        if path.name not in SKIP_FILES and "__pycache__" not in path.parts:
            phrases.extend(_from_python(path))
    for path in sorted((root / "web" / "templates").glob("*.html")) + sorted((root / "web" / "static").rglob("*.js")):
        phrases.extend(_from_template(path))
    seen, unique = set(), []
    for p in sorted(phrases, key=lambda p: (p.where.split(":")[0], int(p.where.rsplit(":", 1)[1]))):
        if (p.where, p.ky) not in seen:
            seen.add((p.where, p.ky))
            unique.append(p)
    return unique


def to_csv(phrases: list[Phrase]) -> str:
    """For the native speaker: where, Russian, Kyrgyz, and two empty columns to fill."""
    out = io.StringIO()
    out.write("﻿")  # Excel opens UTF-8 with Cyrillic correctly
    w = csv.writer(out)
    w.writerow(["№", "Где в коде", "По-русски", "По-кыргызски", "Верно? (да/нет)", "Как правильно"])
    for i, p in enumerate(phrases, 1):
        w.writerow([i, p.where, p.ru, p.ky, "", ""])
    return out.getvalue()
