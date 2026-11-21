"""The mobile app's Kyrgyz texts, for the native speaker's list (joop/ky_phrases.py, /owner/kyrgyz).

The app keeps every text it shows in mobile/lib/core/strings.dart: the Russian set `static const ru = S._(…)`, the
Kyrgyz set `static const ky = S._(…)` with the same names, and small functions `_ruName` / `_kyName` for texts with a
number or a name in them. None of it was written by a native speaker.

The server's image holds joop/ only, so the list is kept here as a snapshot, app_ky_strings.json, made from the Dart
file by `python -m joop.app_strings`. A test fails when the snapshot no longer matches the app's texts and names that
command. Pairs come out in the order of the Kyrgyz set: (line in strings.dart, Kyrgyz, its Russian twin).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DART = Path(__file__).resolve().parent.parent / "mobile" / "lib" / "core" / "strings.dart"
SNAPSHOT = Path(__file__).resolve().parent / "app_ky_strings.json"
WHERE = "mobile/lib/core/strings.dart"
CYRILLIC = re.compile(r"[а-яёңөүА-ЯЁҢӨҮ]")
ENTRY = re.compile(r"^    ([a-zA-Z0-9]+): ", re.M)
FUNCTION = re.compile(r"^String _(ru|ky)([A-Za-z0-9]+)\(", re.M)


def _literals(text: str, offset: int = 0) -> list[tuple[int, str]]:
    """(position, value) of each Dart string literal, comments skipped; adjacent literals ('a' 'b') joined."""
    out: list[tuple[int, str]] = []
    i, last_end = 0, -1
    while i < len(text):
        ch = text[i]
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = len(text) if i < 0 else i
            continue
        if ch in "'\"":
            start, j, value = i, i + 1, []
            while j < len(text) and text[j] != ch:
                if text.startswith("${", j):  # an interpolation, which may hold strings of its own: shown as {…}
                    j = _closing(text, j + 2)
                    value.append("{…}")
                    continue
                if text[j] == "\\" and j + 1 < len(text):
                    value.append({"n": "\n", "t": "\t"}.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                value.append(text[j])
                j += 1
            literal = "".join(value)
            if out and last_end >= 0 and not text[last_end:start].strip():
                out[-1] = (out[-1][0], out[-1][1] + literal)  # 'one ' 'two': one string in Dart
            else:
                out.append((offset + start, literal))
            i = last_end = j + 1
            continue
        i += 1
    return out


def _closing(text: str, i: int) -> int:
    """The position after the } that closes an interpolation opened just before i, strings inside skipped."""
    depth = 1
    while i < len(text) and depth:
        if text[i] in "'\"":
            quote, i = text[i], i + 1
            while i < len(text) and text[i] != quote:
                i = _closing(text, i + 2) if text.startswith("${", i) else i + (2 if text[i] == "\\" else 1)
        elif text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return i


def _block(source: str, name: str) -> tuple[int, str]:
    start = source.index(f"  static const {name} = S._(")
    end = source.index("\n  );", start)
    return start, source[start:end]


def _entries(source: str, name: str) -> dict[str, tuple[int, list[str], str]]:
    """name -> (position, its texts, the function it points to or "")."""
    start, block = _block(source, name)
    found = list(ENTRY.finditer(block))
    out = {}
    for n, m in enumerate(found):
        body = block[m.end():found[n + 1].start() if n + 1 < len(found) else len(block)]
        texts = [t for _, t in _literals(body) if CYRILLIC.search(t)]
        target = re.match(r"\s*(_(?:ru|ky)[A-Za-z0-9]+)\s*,", body)
        out[m.group(1)] = (start + m.start(), texts, target.group(1)[3:] if target else "")
    return out


def _functions(source: str) -> dict[tuple[str, str], tuple[int, list[str]]]:
    """(ru|ky, Name) -> (position, its texts), each function up to the next top-level line."""
    found = list(FUNCTION.finditer(source))
    out = {}
    for n, m in enumerate(found):
        end = found[n + 1].start() if n + 1 < len(found) else len(source)
        rest = source[m.end():end]
        first = rest.find("\n") + 1 or len(rest)  # the signature's own line, then what is indented under it
        nxt = re.compile(r"^(?!\s)\S", re.M).search(rest, first)  # a comment or another top-level line
        body = rest[:nxt.start()] if nxt else rest
        out[(m.group(1), m.group(2))] = (m.start(), [t for _, t in _literals(body) if CYRILLIC.search(t)])
    return out


def pairs(source: str) -> list[tuple[int, str, str]]:
    """(line, Kyrgyz, Russian) for every Kyrgyz text of the app, in the order of the Kyrgyz set."""
    line = lambda at: source.count("\n", 0, at) + 1  # noqa: E731
    ru, ky, functions = _entries(source, "ru"), _entries(source, "ky"), _functions(source)
    out: list[tuple[int, str, str]] = []
    for key, (at, texts, target) in ky.items():
        twin_texts = ru.get(key, (0, [], ""))
        if target:  # a function: _kyName beside _ruName
            at, texts = functions.get(("ky", target), (at, []))
            twin = functions.get(("ru", twin_texts[2] or target), (0, []))[1]
        else:
            twin = twin_texts[1]
        if len(texts) > 1 and all(len(t) < 12 and " " not in t for t in texts) and len(texts) == len(twin) > 6:
            # weekdays, months: one line for the speaker, not twelve
            texts, twin = [", ".join(texts)], [", ".join(twin)]
        for n, text in enumerate(texts):
            if text.strip():
                out.append((line(at), text, twin[n] if len(twin) == len(texts) else " / ".join(twin)))
    return out


def snapshot() -> list[dict]:
    """The list as the server reads it; [] when neither the snapshot nor the app's source is there."""
    if SNAPSHOT.exists():
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return [{"line": n, "ky": ky, "ru": ru} for n, ky, ru in pairs(DART.read_text(encoding="utf-8"))] if DART.exists() else []


def main() -> int:
    rows = [{"line": n, "ky": ky, "ru": ru} for n, ky, ru in pairs(DART.read_text(encoding="utf-8"))]
    SNAPSHOT.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} Kyrgyz texts of the app -> {SNAPSHOT.relative_to(SNAPSHOT.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
