"""Record the demo walk-through as one video, on a server of its own and with the real model.

    python scripts/record_demo.py out/demo --captions en

It starts a server on this machine with an empty database and walks the demo in a browser as a person would: a clinic
signs up; the owner asks the AI in Kyrgyz and in Russian in the test chat and books a visit; the owner confirms the
example data and opens the booking page; a customer books from a phone; the owner sees both bookings. The browser's
screen is recorded, ffmpeg joins the clips under a caption strip with a title and an end card, and one MP4 comes out
with the dialogue beside it as text.

What the video shows of the AI is the test chat of step 2, and there every answer is written by the model while the
recording runs; nobody types answers for it. As for every customer, the code checks a booking the model proposes, saves
it and adds the line with the saved time and doctor to the model's answer. The chat on the site's first page is an
illustration, not the model. The run fails, and no video is kept, when in the test chat

- the model does not answer (the reply customers get then), or the code answers in its place (the time is taken, the
  name or phone is missing);
- the answer to the Kyrgyz question does not name the price list's price as a number of its own («1 500» is not
  «500»), or is in Russian;
- the answer about the nearest free time names a time that «Окна» does not show free on the day it is named for, or
  leaves out the earliest free time;
- no booking for the customer stands among «Предстоящие» on «Записи» at that earliest time (the waiting list and
  cancelled rows do not count);
- an answer is not on the screen when its caption is.

A run against anything but the real model (LLM_PROVIDER=openai with an address that is not https on the internet: the
test of the recorder itself) says «TEST RUN» on the title card, on every caption and in the file's name.

The server gets nothing from this machine's environment but the model's settings (ANTHROPIC_API_KEY, JOOP_MODEL,
LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY) and reads no .env: a founder's bot or a real database cannot leak into it.

Needs Playwright with Chromium (pip install playwright && playwright install chromium) and ffmpeg.
.github/workflows/demo-video.yml runs it by hand and keeps the MP4 as an artifact of the run.
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from joop.agent.engine import (  # noqa: E402
    ASK_CONTACTS_REPLY, ERROR_REPLY, EXTERNAL_DOWN_REPLY, HANDED_OVER_REPLY, TEXT_ONLY_REPLY,
)
from joop.confirmations import clock_times, day_months, named_days, sentences, weekdays  # noqa: E402
from joop.lang import KY_MESSAGE_MARKERS, RU_MESSAGE_MARKERS, looks_kyrgyz, numbers  # noqa: E402

FPS = 25
FRAME = (1920, 1080)
BAND = 90  # the caption strip under the picture
PICTURE = (FRAME[0], FRAME[1] - BAND)  # the owner's window: recorded pixel for pixel
ZOOM = 1.5  # …and drawn one and a half times larger, as on a 1280 × 660 screen: text a hall can read
PHONE = (400, 660)  # the customer's phone, in CSS pixels
PHONE_SHOWN = (600, 990)  # …enlarged by ffmpeg and centred in the frame
# The recorder films CSS pixels, so a larger device scale would not make the picture sharper; CSS zoom does. It is
# used for the panel and the site only: their layout does not depend on a width between 1280 and 1920 pixels. The
# booking page sizes its heading by the window's width, so the phone is filmed as it is.
ZOOM_SCRIPT = ("const s = new CSSStyleSheet(); s.replaceSync('html{zoom:%s}'); "
               "document.adoptedStyleSheets = [...document.adoptedStyleSheets, s];" % ZOOM)
NIGHT, INK, DIM, MINT, AMBER = "#0b1719", "#e4eeeb", "#8aa3a0", "#3fc2a5", "#f0a453"  # the site's colours
CARD_SECONDS = 4.0
ANSWER_WAIT = 150  # seconds a pressed button may take to open the next page: the model's client retries for 120
MODEL_ENV = ("ANTHROPIC_API_KEY", "JOOP_MODEL", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY")
SYSTEM_ENV = ("PATH", "HOME", "LANG", "SYSTEMROOT", "TMPDIR", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
              "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")

CLINIC = "Демо Стоматология"
ASK_PRICE = "Консультация канча турат?"
SERVICE, PRICE = "Консультация и осмотр", "500"  # the price-list item asked about (joop/niches/dental/demo.yaml)
ASK_TIME = "Когда ближайшее свободное время на консультацию?"
ASK_BOOK = "Запишите на самое раннее время. Меня зовут Айбек, телефон 0555 123 456"
SAY_YES = "Да, запишите"
CHAT_CUSTOMER, PAGE_CUSTOMER = "Айбек", "Айгуль"

# key -> (step, caption). One line of the strip each: 80 characters at most (tests/test_record_demo.py).
CAPTIONS = {
    "en": {
        "site": ("Step 1", "A clinic owner opens the site and signs up"),
        "form": ("Step 1", "Name, type of business, phone: that is the whole form"),
        "launch": ("Step 1", "At once: a working AI with an example price list, and a checklist to launch"),
        "chat": ("Step 2", "The owner tries the AI in the test chat, writing as a customer would"),
        "ask_price": ("Step 2", "A question in Kyrgyz: how much is a consultation?"),
        "price": ("Step 2", "The answer is in Kyrgyz, with the price from the price list"),
        "price_plain": ("Step 2", "The answer names the price from the price list"),
        "ask_time": ("Step 2", "A question in Russian: when is the nearest free time?"),
        "time": ("Step 2", "Only real free times are offered"),
        "ask_book": ("Step 2", "The customer asks for the earliest time and gives a name and a phone"),
        "booked": ("Step 2", "The code checks the time and saves the booking; the AI confirms it"),
        "own": ("Step 3", "The owner confirms the price list and the staff as the clinic’s own"),
        "page_on": ("Step 3", "…and opens the booking page for customers"),
        "phone": ("Step 3", "A customer opens the booking page on a phone, from the QR sign"),
        "pick": ("Step 3", "Picks a free time"),
        "contacts": ("Step 3", "Leaves a name and a phone"),
        "done": ("Step 3", "Booked, without a chat or a call"),
        "bookings": ("Step 4", "The owner sees both bookings: from the test chat and from the booking page"),
    },
    "ru": {
        "site": ("Шаг 1", "Владелец клиники открывает сайт и регистрируется"),
        "form": ("Шаг 1", "Название, сфера, телефон — это вся форма"),
        "launch": ("Шаг 1", "Сразу: рабочий ИИ с примером прайса и список шагов до запуска"),
        "chat": ("Шаг 2", "Владелец проверяет ИИ в тестовом чате: пишет как клиент"),
        "ask_price": ("Шаг 2", "Вопрос по-кыргызски: сколько стоит консультация?"),
        "price": ("Шаг 2", "Ответ по-кыргызски, цена — из прайса"),
        "price_plain": ("Шаг 2", "В ответе — цена из прайса"),
        "ask_time": ("Шаг 2", "Вопрос по-русски: когда ближайшее свободное время?"),
        "time": ("Шаг 2", "ИИ предлагает только настоящее свободное время"),
        "ask_book": ("Шаг 2", "Клиент просит самое раннее время и называет имя и телефон"),
        "booked": ("Шаг 2", "Код проверяет время и сохраняет запись, ИИ подтверждает её"),
        "own": ("Шаг 3", "Владелец подтверждает, что прайс и врачи — его собственные"),
        "page_on": ("Шаг 3", "…и открывает страницу записи для клиентов"),
        "phone": ("Шаг 3", "Клиент открывает страницу записи с телефона, по QR на стойке"),
        "pick": ("Шаг 3", "Выбирает свободное время"),
        "contacts": ("Шаг 3", "Оставляет имя и телефон"),
        "done": ("Шаг 3", "Записан — без переписки и звонка"),
        "bookings": ("Шаг 4", "Владелец видит обе записи: из тестового чата и со страницы записи"),
    },
}

CARDS = {
    "en": {
        "eyebrow": "Demo recording",
        "lead": "An AI administrator for small businesses: from sign-up to a booking in four steps",
        "facts": "Recorded automatically on {day} · model: {model} · an example clinic with fictional data",
        "end": "In the test chat (step 2) the AI’s answers were written by the model while this was recorded; the "
               "line with the booked time was added by the code from the saved booking. The chat on the site’s "
               "first page is an illustration.",
        "test": "TEST RUN · not the real model",
        "test_short": "TEST RUN",
        "end_test": "A test of the recorder: the answers came from a stand-in, not from the model.",
        "note": "In the test chat the answers are the model’s own; after a booking the code adds the line with the "
                "saved time and doctor.",
    },
    "ru": {
        "eyebrow": "Запись демо",
        "lead": "ИИ-администратор для малого бизнеса: от регистрации до записи за четыре шага",
        "facts": "Записано автоматически {day} · модель: {model} · клиника-пример, данные вымышлены",
        "end": "В тестовом чате (шаг 2) ответы ИИ написаны моделью во время записи; строку с временем записи "
               "добавил код — из сохранённой записи. Чат на первой странице сайта — иллюстрация.",
        "test": "ТЕСТОВЫЙ ПРОГОН · не настоящая модель",
        "test_short": "ТЕСТОВЫЙ ПРОГОН",
        "end_test": "Проверка самой записи: ответы давала заглушка, а не модель.",
        "note": "В тестовом чате ответы написаны моделью; после записи код добавляет строку с сохранённым "
                "временем и врачом.",
    },
}


class Broken(Exception):
    """The walk did not go as the video says it does: no video is kept."""


@dataclass
class Clip:
    video: Path
    size: tuple[int, int]  # the picture inside the frame, in video pixels
    cut: float  # seconds dropped from the start: the blank page before the first one loaded
    length: float  # seconds kept
    captions: list[tuple[float, float, str]] = field(default_factory=list)  # from, to (seconds of the kept part), key


# --- what a recording may show --------------------------------------------------------------------------------------

_LOCAL_NAMES = (".localhost", ".local", ".internal", ".lan", ".home", ".home.arpa", ".test", ".example", ".invalid")


def public_host(host: str) -> bool:
    """A name or an address out on the internet: not this machine, not a private network, not a bare or local-only
    name (localhost, x.localhost, host.docker.internal), not a number written short («127.1»)."""
    host = (host or "").strip().strip("[]").rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not host or "." not in host or host.endswith(_LOCAL_NAMES):
            return False
        return not all(re.fullmatch(r"\d+|0x[0-9a-f]+", label) for label in host.split("."))
    address = getattr(address, "ipv4_mapped", None) or address
    return address.is_global


def model_of(env: dict) -> tuple[str, bool]:
    """(the model's name for the title card, is this the real model?). Real: Anthropic, or another provider reached
    over https at an address on the internet. Anything else is the recorder's own test with a stand-in."""
    name = (env.get("JOOP_MODEL") or "").strip() or "claude-haiku-5-5"
    if (env.get("LLM_PROVIDER") or "").strip().lower() != "openai":
        return name, True
    url = urlparse((env.get("LLM_BASE_URL") or "").strip())
    return name, url.scheme == "https" and public_host(url.hostname or "")


def is_fallback(reply: str) -> bool:
    """The reply customers get when the model cannot be called (no key, no balance, an outage)."""
    return any(line.strip() and line.strip() in reply for line in ERROR_REPLY.splitlines())


# What the code sends in the model's place. «Это время уже занято» is the start of three sentences of
# joop/agent/engine.py (_try_booking); tests/test_record_demo.py holds it to the engine's real answer.
_ENGINE_WORDS = [ASK_CONTACTS_REPLY, EXTERNAL_DOWN_REPLY, "Извините, это время уже занято",
                 *HANDED_OVER_REPLY.splitlines(), *TEXT_ONLY_REPLY.splitlines()]


def engine_words(reply: str) -> bool:
    """The code answered in the model's place: the proposed time was taken, the name or the phone was missing, the
    chat was handed to a person. True to the product, but not an answer of the AI to film."""
    return any(words.strip() and words.strip() in reply for words in _ENGINE_WORDS)


def names_price(reply: str) -> bool:
    """The price list's price as a number of its own: «500 сом», not «1 500», «3 500», «5000» or a phone number."""
    return PRICE in numbers(reply)


def in_russian(reply: str) -> bool:
    """A Russian answer to the Kyrgyz question. An answer that reads as Kyrgyz (lang.looks_kyrgyz) is not one.
    Otherwise it is Russian when it has two Russian marker words, or no Kyrgyz word at all and a Russian marker, a
    second sentence or a question; the price-list item's own Russian name does not count. So «Консультация — 500
    сом.» and «Консультация 500 сом турат.» pass, «Консультация стоит 500 сом.» and «Стоимость консультации — 500
    сом. Подобрать для вас удобное время?» do not."""
    if looks_kyrgyz(reply):
        return False
    words = re.findall(r"[а-яёңөү]+", re.sub(re.escape(SERVICE), " ", reply, flags=re.I).lower())
    russian = sum(1 for w in words if w in RU_MESSAGE_MARKERS)
    kyrgyz = sum(1 for w in words if w in KY_MESSAGE_MARKERS or re.search("[ңөү]", w))
    return russian >= 2 or (not kyrgyz and (russian >= 1 or len(sentences(reply)) > 1 or "?" in reply))


def free_times(slots_page: str, now: datetime) -> list[tuple[date, str]]:
    """The free times still ahead as «Окна» (/panel/slots) shows them, earliest first: (day, "09:00"). A time that is
    booked, marked busy or closed, or already past, is not one."""
    found = set()
    for line in slots_page.split('<div class="staff-line">')[1:]:
        day = re.search(r'name="day" value="(\d{4}-\d{2}-\d{2})"', line)
        if not day:
            continue  # nothing ahead for this person on this day
        for state, clock in re.findall(r'<span class="slot([^"]*)"[^>]*>\s*(\d{2}:\d{2})', line):
            at = datetime.fromisoformat(f"{day.group(1)}T{clock}")
            if not state.strip() and at > now:
                found.add((at.date(), clock))
    return sorted(found)


def working_hours(slots_page: str) -> tuple[str, ...]:
    """The clinic's opening and closing time, from the same page's «Заполнить по графику» form."""
    return tuple(re.findall(r'id="g-(?:start|end)"[^>]*\bvalue="(\d{2}:\d{2})"', slots_page))


_HOURS_WORDS = re.compile(r"работа|график|режим|открыт|иштей|иш убакт|иш тартиб", re.I)
_CLAUSE = re.compile(r"[;,]|\s(?:и|или|же|жана)\s")


def _coming(day: int, month: int, today: date) -> date:
    """This day and month, as the next date that is not behind us."""
    for year in (today.year, today.year + 1):
        try:
            if date(year, month, day) >= today:
                return date(year, month, day)
        except ValueError:  # 31.02
            break
    return date.max


def times_problem(reply: str, free: list[tuple[date, str]], today: date, hours: tuple[str, ...] = ()) -> str:
    """Why this reply must not be filmed as the answer to «when is the nearest free time?»; "" when it may be.

    Every time of day it names has to be free (`free`, from free_times) on a day named with it: in the same part of
    the sentence (parts end at a comma, a semicolon, «и», «или»), else the part before, else the part after; a
    sentence that names no day speaks of the last day named before it, and with none, of the nearest day with free
    time. A weekday said by name counts as each of its dates ahead. A date and a weekday said together, in one part
    or in two side by side («в воскресенье, 28.11»), have to agree. And the earliest free time has to be among the
    times named: that is what was asked. The clinic's opening and closing time (`hours`) in a sentence about working
    hours are not offers. A day named without a time offers nothing and is not checked."""
    if not free:
        return "«Окна» shows no free time ahead"
    open_, last_day = set(free), max(d for d, _t in free)
    earlier: set[date] = {free[0][0]}  # the days a time without a day of its own belongs to
    offered: set[tuple[date, str]] = set()
    for sentence in sentences(reply):
        about_hours = bool(_HOURS_WORDS.search(sentence))
        parts, said = [], []  # (times, days) and (dates, weekdays by name) of each part
        for clause in _CLAUSE.split(sentence):
            times = clock_times(clause) - (set(hours) if about_hours else set())
            dated = {_coming(d, m, today) for d, m in day_months(clause)}
            named = weekdays(clause)
            days = dated | {_coming(d, m, today) for d, m in named_days(clause, today)}
            if not days and named:
                span = range((last_day - today).days + 1)
                days = {today + timedelta(days=i) for i in span if (today + timedelta(days=i)).weekday() in named}
            parts.append((times, days))
            said.append((dated, named))
        for i, (dated, named) in enumerate(said):
            beside = [n for d, n in said[max(i - 1, 0):i + 2] if n and not d] if dated and not named else []
            for week in [named] if named else beside:
                if any(d.weekday() not in week for d in dated):
                    return f"«{sentence}» names a date with another day of the week than its own"
        for i, (times, days) in enumerate(parts):
            if not times:
                continue
            before = next((d for _t, d in reversed(parts[:i]) if d), set())
            after = next((d for _t, d in parts[i + 1:] if d), set())
            scope = days or before or after or earlier
            for clock in sorted(times):
                if not any((d, clock) in open_ for d in scope):
                    on = ", ".join(f"{d:%d.%m}" for d in sorted(scope))
                    return f"«{sentence}» names {clock} on {on}: «Окна» shows no such free time"
            offered |= {(d, clock) for d in scope for clock in times if (d, clock) in open_}
        named_here = [d for _t, d in parts if d]
        if named_here:
            earlier = named_here[-1]
    if not offered:
        return "it names no time of day (written as 09:00)"
    if free[0] not in offered:
        return f"the earliest free time, {free[0][0]:%d.%m} {free[0][1]}, is not among the times it names"
    return ""


def upcoming(bookings_page: str) -> list[str]:
    """The bookings that stand under «Предстоящие» on «Записи» (/panel/bookings), each row as plain text («Сб 28.11
    09:00 Айбек …»). Not the cancelled rows, not the past ones, not the waiting list below them."""
    after = bookings_page.split("<h2>Предстоящие</h2>", 1)
    if len(after) < 2:
        return []
    rows = re.findall(r'<tr class="([^"]*)">(.*?)</tr>', after[1].split("</section>", 1)[0], re.S)
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", row)).split()) for state, row in rows if "cancelled" not in state]


def booked(bookings_page: str, name: str) -> str:
    """This customer's standing booking as «Записи» shows it, or ""."""
    return next((row for row in upcoming(bookings_page) if name in row), "")


def errors_in(log: str, last: int = 3) -> str:
    """The server's own words about what went wrong: the last lines of its log that name an error (the model
    provider's answer among them: «Your credit balance is too low», an invalid key), each cut to 300 characters. A
    traceback's line of source (`raise LLMError(...)`) is not one: it would push the provider's line out."""
    lines = [line.strip()[:300] for line in log.splitlines()
             if re.search(r"Error|error code|credit balance", line) and not line.strip().startswith("raise ")]
    return "\n".join(dict.fromkeys(lines[-last:]))  # a retry repeats the same line


def verdict(problem: Exception, log: str) -> str:
    """What a walk that stopped is reported as: its own words when it stopped itself (Broken), else the error's kind
    and first words (a browser's timeout, a page that changed), and under them what the server logged."""
    what = str(problem) if isinstance(problem, Broken) else f"{type(problem).__name__}: {str(problem).strip()[:400]}"
    said = errors_in(log)
    return f"{what}\nThe server's log says:\n{said}" if said else what


def windows(marks: list[tuple[float, str]], start: float, end: float) -> list[tuple[float, float, str]]:
    """Captions said at these moments, as (from, to, key) in seconds of a clip that runs from `start` to `end`:
    each one stays until the next is said."""
    out = []
    for i, (at, key) in enumerate(marks):
        until = marks[i + 1][0] if i + 1 < len(marks) else end
        a, b = max(at, start) - start, min(until, end) - start
        if b - a > 0.05:
            out.append((round(a, 2), round(b, 2), key))
    return out


def graph(clip: Clip) -> tuple[str, str]:
    """(ffmpeg's filter graph for one clip, the label of its result): the picture on the dark frame, each caption's
    strip (inputs 1, 2, … in the order of clip.captions) laid under it while that caption is said."""
    w, h = clip.size
    parts = [f"[0:v]fps={FPS},scale={w}:{h}:flags=lanczos,pad={FRAME[0]}:{FRAME[1]}:{(FRAME[0] - w) // 2}:0:color=0x{NIGHT[1:]},setsar=1[s0]"]
    for i, (a, b, _key) in enumerate(clip.captions, 1):
        parts.append(f"[s{i - 1}][{i}:v]overlay=0:{FRAME[1] - BAND}:enable='between(t,{a:.2f},{b:.2f})'[s{i}]")
    return ";".join(parts), f"[s{len(clip.captions)}]"


def strip_html(step: str, text: str, mark: str = "") -> str:
    warn = f'<span class="w">{html.escape(mark)}</span>' if mark else ""
    return f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/fonts/fonts.css">
<style>html,body{{margin:0;background:{NIGHT}}}
.s{{width:{FRAME[0]}px;height:{BAND}px;box-sizing:border-box;padding:0 48px;display:flex;align-items:center;gap:28px;
font-family:'Golos Text',Arial,sans-serif;white-space:nowrap;border-top:2px solid #12262a}}
.k{{color:{MINT};font-weight:600;font-size:26px;letter-spacing:3px;text-transform:uppercase}}
.t{{color:{INK};font-weight:500;font-size:34px}}
.w{{margin-left:auto;color:{AMBER};font-weight:700;font-size:24px;letter-spacing:2px}}</style>
<div class="s"><span class="k">{html.escape(step)}</span><span class="t">{html.escape(text)}</span>{warn}</div>"""


def card_html(eyebrow: str, lead: str, facts: str, mark: str = "") -> str:
    warn = f'<p class="w">{html.escape(mark)}</p>' if mark else ""
    return f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/fonts/fonts.css">
<style>html,body{{margin:0;background:{NIGHT}}}
.c{{width:{FRAME[0]}px;height:{FRAME[1]}px;box-sizing:border-box;padding:128px;display:flex;flex-direction:column;
justify-content:space-between;font-family:'Golos Text',Arial,sans-serif;color:{INK}}}
p{{margin:0}} .e{{color:{MINT};font-weight:600;font-size:28px;letter-spacing:4px;text-transform:uppercase}}
h1{{margin:0 0 40px;font-family:'Unbounded','Arial Black',sans-serif;font-weight:700;font-size:168px;letter-spacing:-4px;line-height:1}}
.l{{font-size:48px;line-height:1.3;max-width:1400px}} .f{{color:{DIM};font-size:30px;line-height:1.4}}
.w{{color:{AMBER};font-weight:700;font-size:44px;letter-spacing:2px;margin-top:32px}}</style>
<div class="c"><p class="e">{html.escape(eyebrow)}</p><div><h1>Joop AI</h1><p class="l">{html.escape(lead)}</p>{warn}</div>
<p class="f">{html.escape(facts)}</p></div>"""


def file_name(lang: str, real: bool) -> str:
    return f"joop-demo-{'' if real else 'TEST-'}{lang}.mp4"


def pictures_of(lang: str, model: str, real: bool, day: str) -> dict[str, tuple[str, int]]:
    """Every still of the film as name -> (html, height): a strip per caption, the title card and the end card. A run
    that is not on the real model carries its mark on each of them, and its end card says so instead of the claim."""
    cards = CARDS[lang]
    mark, short = ("", "") if real else (cards["test"], cards["test_short"])
    pages = {key: (strip_html(step, text, short), BAND) for key, (step, text) in CAPTIONS[lang].items()}
    facts = cards["facts"].format(day=day, model=model)
    pages["title"] = (card_html(cards["eyebrow"], cards["lead"], facts, mark), FRAME[1])
    pages["end"] = (card_html(cards["eyebrow"], cards["end"] if real else cards["end_test"], facts, mark), FRAME[1])
    return pages


def transcript(talk: list[tuple[str, str]], lang: str, model: str, real: bool, day: str) -> str:
    """The dialogue of the test chat as text, to lie beside the film."""
    cards = CARDS[lang]
    lines = [f"Joop AI, demo recording of {day}. Model: {model}{'' if real else ' — ' + cards['test']}.",
             cards["note"] if real else cards["end_test"], ""]
    lines += [f"{'Customer' if who == 'customer' else 'AI'}: {text}" for who, text in talk]
    return "\n".join(lines) + "\n"


# --- the server -----------------------------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def server_env(folder: Path, port: int, machine: dict) -> dict:
    """The environment of the recorder's server: of the machine's own, what a program needs to run and reach the
    network, and the model's settings. Nothing else gets in: no founder's bot, no channel tokens, no real database;
    JOOP_ENV_FILE names a file that does not exist, so no .env is read either. The scheduler is off: reminders and
    summaries have nobody to go to here."""
    env = {k: machine[k] for k in SYSTEM_ENV if k in machine}
    env.update({k: machine[k] for k in MODEL_ENV if machine.get(k)})
    env.update(PYTHONPATH=str(ROOT), JOOP_ENV_FILE=str(folder / "no.env"), DATABASE_URL=f"sqlite:///{folder / 'demo.db'}",
               SESSION_SECRET=secrets.token_hex(32), SECURE_COOKIES="0", PUBLIC_BASE_URL=f"http://127.0.0.1:{port}",
               OWNER_PASSWORD=secrets.token_urlsafe(18), SCHEDULER_ENABLED="0")
    return env


def start_server(folder: Path, port: int) -> subprocess.Popen:
    """A server of its own, with an empty database in `folder`."""
    env = server_env(folder, port, dict(os.environ))
    log = open(folder / "server.log", "w")
    said = lambda: (folder / "server.log").read_text(errors="replace")[-800:]  # noqa: E731
    done = subprocess.run([sys.executable, "-m", "joop", "migrate"], env=env, cwd=folder, stdout=log, stderr=subprocess.STDOUT)
    if done.returncode:
        raise Broken("The empty database could not be made: " + said())
    server = subprocess.Popen([sys.executable, "-m", "joop", "serve", "--host", "127.0.0.1", "--port", str(port)],
                              env=env, cwd=folder, stdout=log, stderr=subprocess.STDOUT)
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this machine's proxy is not on the way
    for _ in range(120):
        if server.poll() is not None:
            break
        try:
            with direct.open(f"http://127.0.0.1:{port}/health", timeout=2) as answer:
                if answer.status == 200:
                    return server
        except OSError:
            time.sleep(0.5)
    server.kill()
    raise Broken("The server did not start: " + said())


# --- the browser ----------------------------------------------------------------------------------------------------

# How much of the last answer is on the screen (0…1), after the last question is brought to the top of the window,
# or, when the answer does not fit under it, the answer's end to the bottom. Measured against a box that fills the
# window, in the page's own units: the page is drawn enlarged (ZOOM).
_SHOW_ANSWER = """() => {
  const last = s => [...document.querySelectorAll(s)].pop();
  const question = last('.msgs .msg.customer'), answer = last('.msgs .msg.ai');
  if (!question || !answer) return 0;
  const probe = document.createElement('div');
  probe.style.cssText = 'position:fixed;inset:0;visibility:hidden;pointer-events:none';
  document.body.appendChild(probe);
  const seen = el => { const w = probe.getBoundingClientRect(), r = el.getBoundingClientRect();
    return r.height ? Math.max(0, Math.min(r.bottom, w.bottom) - Math.max(r.top, w.top)) / r.height : 0; };
  question.style.scrollMarginTop = '24px';
  question.scrollIntoView({block: 'start'});
  if (seen(answer) < 0.99) { answer.style.scrollMarginBottom = '24px'; answer.scrollIntoView({block: 'end'}); }
  const part = seen(answer);
  probe.remove();
  return part;
}"""


class Shot:
    """One recorded browser window: its page, its video and the captions said while it ran."""

    def __init__(self, browser, folder: Path, base: str = "", mobile: bool = False, storage=None) -> None:
        window = PHONE if mobile else PICTURE
        self.base = base
        self.size = PHONE_SHOWN if mobile else PICTURE  # in the film
        self.context = browser.new_context(
            viewport={"width": window[0], "height": window[1]}, device_scale_factor=1, locale="ru-RU", color_scheme="light",
            is_mobile=mobile, has_touch=mobile, storage_state=storage, record_video_dir=str(folder),
            record_video_size={"width": window[0], "height": window[1]})
        if not mobile:
            self.context.add_init_script(ZOOM_SCRIPT)
        self.page = self.context.new_page()
        self.created = time.monotonic()
        self.loaded: float | None = None  # the first page was on the screen
        self.landed: float | None = None  # the page now on the screen appeared
        self.marks: list[tuple[float, str]] = []

    def settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # a page that keeps a connection open: it is loaded enough
            pass
        self.page.wait_for_timeout(400)

    def open(self, url: str) -> None:
        self.page.goto(url)
        self.landed = time.monotonic()
        self.settle()
        if self.loaded is None:
            self.loaded = time.monotonic()

    def say(self, key: str, landed: bool = False) -> None:
        """This caption from now on; `landed`: from the moment the page on the screen appeared, so the words do not
        change a second after the picture."""
        at = self.landed if landed and self.landed is not None else time.monotonic()
        self.marks.append((max(at, self.marks[-1][0]) if self.marks else at, key))

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def point(self, target) -> None:
        """The video has no mouse pointer: an amber outline shows what is pressed next."""
        target.scroll_into_view_if_needed()
        target.evaluate("el => { el.style.outline = '4px solid #f0a453'; el.style.outlineOffset = '3px'; }")
        self.hold(0.7)

    def press(self, target, leaves: bool = True, arrived=None) -> None:
        """Press a link or a button; `leaves`: another page opens. The model may think for a long time before it
        does (ANSWER_WAIT): the click itself does not wait, or its own half a minute would be the limit. `arrived`
        is called as soon as the new page is there, before it is counted as on the screen: a caption said for
        «the page that landed» then starts with what `arrived` put in the window, not a second earlier."""
        self.point(target)
        if leaves:
            with self.page.expect_navigation(timeout=ANSWER_WAIT * 1000):
                target.click(no_wait_after=True)
            if arrived:
                arrived()
            self.landed = time.monotonic()
            self.settle()
        else:
            target.click()
            target.evaluate("el => { el.style.outline = ''; }")
            self.hold(0.3)

    def write(self, selector: str, text: str) -> None:
        field_ = self.page.locator(selector).first
        field_.scroll_into_view_if_needed()
        field_.click()
        self.page.keyboard.type(text, delay=45)
        self.hold(0.3)

    def panel(self, path: str) -> str:
        """A page of the panel as the signed-in owner gets it, without showing it."""
        return self.context.request.get(self.base + path).text()

    def ask(self, text: str, key: str) -> str:
        """Type a customer's message into the test chat, send it and return the AI's reply as the chat shows it ("" when
        it shows none). The model answers while the page loads: the wait in the video is the model's own. The page
        comes back scrolled to the message field, with the answer above the window: the question and the answer are
        brought onto the screen, and an answer that is not on it is not filmed."""
        answers = self.page.locator(".msgs .msg.ai")
        before = answers.count()
        self.say(key)
        self.write("#text", text)
        self.hold(0.8)
        self.press(self.page.locator("form#end button[type=submit]"), arrived=lambda: self.page.evaluate(_SHOW_ANSWER))
        if answers.count() <= before:
            return ""
        seen = self.page.evaluate(_SHOW_ANSWER)  # again, now that the page is at rest (fonts, the field's focus)
        self.hold(0.3)
        if seen < 0.99:
            raise Broken(f"The answer to «{text}» is not on the screen: {seen:.0%} of it is in the window")
        return answers.last.evaluate("el => { const copy = el.cloneNode(true); copy.querySelectorAll('.meta').forEach(m => m.remove()); "
                                     "return copy.textContent.trim(); }")

    def close(self) -> Clip:
        end = time.monotonic()
        video = self.page.video
        self.context.close()  # the video file is complete only now
        start = self.loaded or self.created
        return Clip(Path(video.path()), self.size, round(start - self.created, 2), round(end - start, 2),
                    windows(self.marks, start, end))


def answer(desk, text: str, key: str, talk: list[tuple[str, str]]) -> str:
    """Ask in the test chat and return what the model answered; anything else in its place stops the recording."""
    reply = desk.ask(text, key)
    talk += [("customer", text), ("ai", reply)]
    if not reply or is_fallback(reply):
        raise Broken("The model did not answer (the fallback reply or nothing): check the key and the balance. "
                     f"After «{text}» the chat shows: {reply[:200]!r}")
    if engine_words(reply):
        raise Broken(f"After «{text}» the code answered in the model's place, and that is not the AI's answer to film: {reply[:300]!r}")
    return reply


def chat_scene(desk, talk: list[tuple[str, str]], now: datetime) -> None:
    """Step 2, the test chat on the real model: a price in Kyrgyz, the nearest free time in Russian, a booking. Each
    answer is checked against the panel before its caption is said; a wrong one raises Broken.

    `desk` is the owner's window: ask(text, key) -> the AI's reply as the chat shows it, panel(path) -> a panel
    page's html, say(key, landed), hold(seconds). `now` is the clinic's time, as «Окна» counts it."""
    reply = answer(desk, ASK_PRICE, "ask_price", talk)
    if not names_price(reply) or in_russian(reply):
        raise Broken(f"To «{ASK_PRICE}» the AI must name {PRICE} som, and not in Russian; it said: {reply[:300]!r}")
    desk.say("price" if looks_kyrgyz(reply) else "price_plain", landed=True)  # the caption says only what the reply shows
    desk.hold(6)
    schedule = desk.panel("/panel/slots")
    free = free_times(schedule, now)
    reply = answer(desk, ASK_TIME, "ask_time", talk)
    problem = times_problem(reply, free, now.date(), working_hours(schedule))
    if problem:
        raise Broken(f"To «{ASK_TIME}» the AI must offer real free times, the earliest among them; {problem}. It said: {reply[:300]!r}")
    desk.say("time", landed=True)
    desk.hold(6)
    reply = answer(desk, ASK_BOOK, "ask_book", talk)
    if not booked(desk.panel("/panel/bookings"), CHAT_CUSTOMER):
        desk.hold(4)
        reply = answer(desk, SAY_YES, "ask_book", talk)  # the AI asked to confirm: the customer does, once
    row = booked(desk.panel("/panel/bookings"), CHAT_CUSTOMER)
    if not row:
        raise Broken(f"The AI did not book {CHAT_CUSTOMER}: «Записи» has no such upcoming booking. Its last reply: {reply[:300]!r}")
    first = f"{free[0][0]:%d.%m} {free[0][1]}"
    if first not in row:
        raise Broken(f"{CHAT_CUSTOMER} asked for the earliest time, {first}, and «Записи» shows: {row[:120]!r}")
    desk.say("booked", landed=True)
    desk.hold(7)


def walk(browser, base: str, folder: Path, now: datetime) -> tuple[list[Clip], list[tuple[str, str]]]:
    """The demo, recorded: three clips (the owner, the customer's phone, the owner again) and the dialogue."""
    talk: list[tuple[str, str]] = []

    # 1. sign-up
    owner = Shot(browser, folder, base)
    owner.open(base + "/")
    owner.say("site")
    owner.hold(3.5)
    owner.press(owner.page.locator('a[href="/signup"]').first)
    owner.say("form", landed=True)
    owner.write("input[name=name]", CLINIC)
    owner.page.select_option("select[name=niche]", "dental")
    owner.hold(0.5)
    owner.write("input[name=contact_name]", "Бектур")
    owner.write("input[name=phone]", "0555 010 203")
    owner.write("input[name=password]", secrets.token_urlsafe(12))
    owner.press(owner.page.locator('form[action="/signup"] button[type=submit]'))
    if "/panel" not in owner.page.url:
        raise Broken(f"Sign-up did not open the panel: {owner.page.url}")
    owner.say("launch", landed=True)
    owner.hold(5)

    # 2. the test chat, on the real model
    owner.open(base + "/panel/try")
    owner.say("chat", landed=True)
    owner.hold(3)
    chat_scene(owner, talk, now)

    # 3. the example becomes the clinic's own data, the booking page opens
    owner.open(base + "/panel")
    owner.say("own", landed=True)
    own = owner.page.locator('form[action="/panel/example/ok"] button')
    if not own.count():
        raise Broken("The dashboard has no «Это наши настоящие данные» button")
    owner.hold(1.5)
    owner.press(own.first)
    owner.hold(2.5)
    owner.open(base + "/panel/menu")
    owner.say("page_on", landed=True)
    for name in ("enabled", "self_booking"):
        box = owner.page.locator(f"input[name={name}]").first
        if not box.is_checked():
            owner.press(box, leaves=False)
    owner.press(owner.page.locator("form:has(input[name=self_booking]) button[type=submit]").first)
    found = re.search(r"/m/([a-z0-9-]+)/book", owner.page.content())
    if not found:
        raise Broken("The booking page's address is not on «Прайс онлайн» after saving")
    owner.hold(3)
    signed_in = owner.context.storage_state()
    clips = [owner.close()]

    # the customer, on a phone
    phone = Shot(browser, folder, base, mobile=True)
    phone.open(f"{base}/m/{found.group(1)}/book")
    phone.say("phone", landed=True)
    phone.hold(3.5)
    times = phone.page.locator('a[href*="slot="]')
    if times.count() < 3:
        raise Broken(f"The booking page offers {times.count()} free times; the example opens dozens")
    phone.say("pick")
    phone.press(times.nth(2))
    phone.say("contacts", landed=True)
    phone.write("input[name=name]", PAGE_CUSTOMER)
    phone.write("input[name=phone]", "0555 777 888")
    phone.hold(1.5)  # with the typing above: longer than the form's shortest time for a person
    phone.press(phone.page.locator("form.book button[type=submit]").first)
    if "/book/" not in phone.page.url:  # a booking made opens /m/<clinic>/book/<its own page>; a refused one does not
        raise Broken("The booking page did not take the booking: " + phone.page.locator("body").inner_text()[:300])
    phone.say("done", landed=True)
    phone.hold(5)
    clips.append(phone.close())

    # 4. the owner again
    owner = Shot(browser, folder, base, storage=signed_in)
    owner.open(base + "/panel/bookings")
    listed = owner.page.content()
    if not booked(listed, CHAT_CUSTOMER) or not booked(listed, PAGE_CUSTOMER):
        raise Broken(f"«Записи» does not show both bookings among the upcoming ones: {upcoming(listed)}")
    owner.say("bookings", landed=True)
    owner.hold(7)
    clips.append(owner.close())
    return clips, talk


# --- the film -------------------------------------------------------------------------------------------------------


def render(browser, base: str, pages: dict[str, tuple[str, int]], folder: Path) -> dict[str, Path]:
    """Captions and cards as pictures, in the site's own fonts: name -> (html, height) becomes name -> PNG. The html is
    served under the server's address, so /static/fonts loads as on the site."""
    def serve(body: str):
        def answer_(route) -> None:  # one parameter: with two, Playwright passes the request as the second
            route.fulfill(content_type="text/html; charset=utf-8", body=body)
        return answer_

    out: dict[str, Path] = {}
    context = browser.new_context(viewport={"width": FRAME[0], "height": FRAME[1]}, device_scale_factor=1)
    page = context.new_page()
    for name, (body, height) in pages.items():
        address = f"{base}/__film/{name}"
        page.route(address, serve(body))
        page.set_viewport_size({"width": FRAME[0], "height": height})
        page.goto(address)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(150)
        out[name] = folder / f"{name}.png"
        page.screenshot(path=str(out[name]))
    context.close()
    return out


# The cards and the clips are encoded alike down to the stream's header (square pixels by setsar in each graph, the
# same colour description), so the parts join without re-encoding into a file every player reads the same way.
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
          "-colorspace", "bt470bg", "-color_range", "tv", "-chroma_sample_location", "center",
          "-video_track_timescale", "12800", "-an"]


def run_ffmpeg(args: list[str]) -> None:
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if done.returncode:
        raise Broken("ffmpeg: " + done.stderr[-1500:])


def film(clips: list[Clip], pictures: dict[str, Path], folder: Path, out: Path) -> float:
    """Title card, the clips under their captions, end card: one MP4 at `out`. Returns its length in seconds; raises
    Broken when it did not come out as the frame and the clips say it must."""
    parts = []

    def still(name: str) -> None:
        parts.append(folder / f"part{len(parts)}.mp4")
        run_ffmpeg(["-loop", "1", "-framerate", str(FPS), "-t", str(CARD_SECONDS), "-i", str(pictures[name]),
                    "-vf", "setsar=1", *ENCODE, str(parts[-1])])

    still("title")
    for clip in clips:
        parts.append(folder / f"part{len(parts)}.mp4")
        strips = [arg for _a, _b, key in clip.captions for arg in ("-i", str(pictures[key]))]
        graph_, result = graph(clip)
        run_ffmpeg(["-ss", str(clip.cut), "-t", str(clip.length), "-i", str(clip.video), *strips,
                    "-filter_complex", graph_, "-map", result, *ENCODE, str(parts[-1])])
    still("end")
    (folder / "parts.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(folder / "parts.txt"), "-c", "copy", "-movflags", "+faststart", str(out)])
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.split()
    width, height = (int(x) for x in probe[0].split(",")[:2])
    length = float(probe[1])
    expected = 2 * CARD_SECONDS + sum(c.length for c in clips)
    if (width, height) != FRAME or abs(length - expected) > 3:
        raise Broken(f"The film came out {width}×{height}, {length:.1f} s; expected {FRAME[0]}×{FRAME[1]}, about {expected:.1f} s")
    return length


def record(out: Path, lang: str) -> Path:
    from playwright.sync_api import sync_playwright

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise Broken(f"{tool} is not installed")
    model, real = model_of(dict(os.environ))
    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Bishkek")).replace(tzinfo=None)  # the clinic's time
    day = f"{now:%d.%m.%Y}"
    target = out / file_name(lang, real)
    for old in (target, target.with_suffix(".txt")):  # an earlier run's film must not pass for this one's
        old.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="joop-demo-") as tmp:
        folder = Path(tmp)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = start_server(folder, port)
        problem: Exception | None = None
        try:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    try:
                        clips, talk = walk(browser, base, folder, now)
                        pictures = render(browser, base, pictures_of(lang, model, real, day), folder)
                    except Exception as error:  # held until the browser is closed: raised inside, it ends in Playwright's own traceback
                        problem = error
                    browser.close()
            except Exception as error:
                problem = problem or error
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        if problem is not None:  # the server knows why the model did not answer
            raise Broken(verdict(problem, (folder / "server.log").read_text(errors="replace"))) from None
        length = film(clips, pictures, folder, folder / "film.mp4")  # moved out only when it is whole and right
        out.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder / "film.mp4"), target)
    target.with_suffix(".txt").write_text(transcript(talk, lang, model, real, day), encoding="utf-8")
    print(f"{target}: {length:.0f} s, {target.stat().st_size / 1e6:.1f} MB; the dialogue is in {target.with_suffix('.txt').name}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the demo walk-through as one MP4, on the real model.")
    parser.add_argument("out", help="folder for joop-demo-<captions>.mp4 and the dialogue as text")
    parser.add_argument("--captions", choices=sorted(CAPTIONS), default="en", help="language of the captions and cards")
    args = parser.parse_args()
    try:
        record(Path(args.out), args.captions)
    except Broken as problem:
        print(f"No video: {problem}", file=sys.stderr)
        return 1
    except Exception as problem:  # the recorder's own mistake: the trace for whoever fixes it, the verdict last
        traceback.print_exc()
        print(f"No video: the recorder itself failed ({type(problem).__name__}: {str(problem).strip()[:300]})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
