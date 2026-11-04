"""The free chat audit: a prospect's WhatsApp export in, the numbers they lose out.

The strategy's first touch (docs: «Joop AI — стратегия с нуля», "аудит переписки"): instead of "we have an AI",
the founder offers to count what the salon loses in its own chats. The owner exports a few WhatsApp chats
(«Ещё» → «Экспорт чата» → «Без файлов») and drops the .txt files on /audit. Code parses them, works out who the
business is, and shows: how many customer messages came outside working hours, how long replies took, how many
questions about the price waited more than an hour, how many dialogues ended with the customer's last message.
No model call, nothing is stored: the parsed chats live in memory for a quarter of an hour so the owner can leave
a phone number for the demo on their price list, then they are gone. Customers' names never appear in the report.

Export formats seen in the wild and parsed here: Android «04.11.2026, 12:03 - Имя: текст», iOS
«[04.11.2026, 12:03:15] Имя: текст» (often with an invisible left-to-right mark first), US «11/4/26, 7:02 PM - Name:
text»; a message's extra lines follow without a timestamp; system lines have no «Имя:» part.
"""

from __future__ import annotations

import re
import secrets
import statistics
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time
from threading import Lock

_LINE = re.compile(r"^‎?\[?(?P<ts>\d{1,4}[./-]\d{1,2}[./-]\d{2,4},? \d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp][Mm])?)\]?\s?[-–]?\s?"
                   r"(?P<rest>.*)$")
_FORMATS = ("%d.%m.%Y, %H:%M:%S", "%d.%m.%Y, %H:%M", "%d.%m.%y, %H:%M:%S", "%d.%m.%y, %H:%M", "%d/%m/%Y, %H:%M:%S", "%d/%m/%Y, %H:%M",
            "%d/%m/%y, %H:%M:%S", "%d/%m/%y, %H:%M", "%m/%d/%y, %I:%M %p", "%m/%d/%y, %I:%M:%S %p", "%m/%d/%Y, %I:%M %p",
            "%m/%d/%y, %H:%M", "%Y-%m-%d, %H:%M:%S", "%Y-%m-%d, %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M")
_PRICE = re.compile(r"(сколько|цена|цены|стоит|стоимост|прайс|расценк|канча|баасы|баа\b|тариф)", re.I)
_MEDIA = re.compile(r"^<.*>$|^‎?(Без медиафайлов|<Media omitted>|image omitted|audio omitted|‎)", re.I)
TTL = 15 * 60  # seconds the parsed chats stay in memory for the lead form
MAX_FILES, MAX_BYTES = 30, 5 * 1024 * 1024


@dataclass
class Msg:
    at: datetime
    sender: str
    text: str


def _parse_ts(raw: str) -> datetime | None:
    raw = raw.replace(" ", " ").replace(" ", " ").strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse(text: str) -> list[Msg]:
    """Messages of one exported chat, in order; system lines dropped; continuation lines joined."""
    out: list[Msg] = []
    for line in text.splitlines():
        m = _LINE.match(line.strip("﻿"))
        if m and (at := _parse_ts(m.group("ts"))) is not None:
            rest = m.group("rest").lstrip("‎ ")
            sender, sep, body = rest.partition(": ")
            if sep and 0 < len(sender.strip()) <= 60:
                out.append(Msg(at, sender.strip(), body.strip()))
            continue  # a system line
        if out and line.strip():
            out[-1].text += "\n" + line.strip()
    return out


def guess_business(chats: list[list[Msg]]) -> str:
    """The sender who takes part in the most chats (ties: the most messages) — a business talks to everybody."""
    presence: dict[str, int] = {}
    count: dict[str, int] = {}
    for chat in chats:
        for name in {m.sender for m in chat}:
            presence[name] = presence.get(name, 0) + 1
        for m in chat:
            count[m.sender] = count.get(m.sender, 0) + 1
    if not count:
        return ""
    if len(chats) == 1:  # one chat: the one who answers second is usually the business; the one who writes first, the customer
        chat = chats[0]
        senders = list(dict.fromkeys(m.sender for m in chat))
        return senders[1] if len(senders) > 1 else senders[0]
    return max(count, key=lambda n: (presence[n], count[n]))


@dataclass
class Report:
    business: str = ""
    dialogues: int = 0
    customer_messages: int = 0
    business_messages: int = 0
    off_hours: int = 0
    answered: int = 0
    unanswered: int = 0
    ended_by_customer: int = 0
    median_reply_minutes: int | None = None
    within_15_min: int = 0
    over_an_hour: int = 0
    price_questions: int = 0
    price_waited_over_an_hour: int = 0
    first_day: date | None = None
    last_day: date | None = None
    senders: list[str] = field(default_factory=list)

    @property
    def off_hours_pct(self) -> int:
        return round(100 * self.off_hours / self.customer_messages) if self.customer_messages else 0

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1 if self.first_day and self.last_day else 0


def _hhmm(value: str, default: time) -> time:
    try:
        h, m = value.strip().split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return default


def report(chats: list[list[Msg]], business: str, work_start: str, work_end: str) -> Report:
    start, end = _hhmm(work_start, time(10, 0)), _hhmm(work_end, time(20, 0))
    r = Report(business=business)
    replies: list[float] = []
    names: dict[str, int] = {}
    for chat in chats:
        if not chat or not any(m.sender != business for m in chat):
            continue
        r.dialogues += 1
        for m in chat:
            names[m.sender] = names.get(m.sender, 0) + 1
            r.first_day = min(r.first_day or m.at.date(), m.at.date())
            r.last_day = max(r.last_day or m.at.date(), m.at.date())
        i = 0
        while i < len(chat):
            m = chat[i]
            if m.sender == business:
                r.business_messages += 1
                i += 1
                continue
            r.customer_messages += 1
            t = m.at.time()
            if not (start <= t < end) if start < end else (end <= t < start):
                r.off_hours += 1
            is_price = bool(_PRICE.search(m.text)) and not _MEDIA.match(m.text)
            r.price_questions += is_price
            # the customer's turn: this message and any that follow before the business speaks
            j = i
            while j + 1 < len(chat) and chat[j + 1].sender != business:
                j += 1
                r.customer_messages += 1
                r.off_hours += 1 if not (start <= chat[j].at.time() < end) else 0
                if _PRICE.search(chat[j].text) and not _MEDIA.match(chat[j].text):
                    r.price_questions += 1
                    is_price = True
            if j + 1 < len(chat):
                wait = (chat[j + 1].at - m.at).total_seconds() / 60
                replies.append(wait)
                r.answered += 1
                r.within_15_min += wait <= 15
                r.over_an_hour += wait > 60
                r.price_waited_over_an_hour += is_price and wait > 60
            else:
                r.unanswered += 1
                r.ended_by_customer += 1
                r.price_waited_over_an_hour += is_price
            i = j + 1
    if replies:
        r.median_reply_minutes = int(statistics.median(replies))
    r.senders = sorted(names, key=lambda n: -names[n])[:6]
    return r


# --- the parsed chats wait a quarter of an hour for the lead form --------------------------------

_cache: dict[str, tuple[float, list[list[Msg]], Report]] = {}
_lock = Lock()
_last = ""


def keep(chats: list[list[Msg]], rep: Report) -> str:
    global _last
    token = secrets.token_urlsafe(12)
    with _lock:
        now = _time.monotonic()
        for k in [k for k, (exp, _, _) in _cache.items() if exp < now]:
            del _cache[k]
        while len(_cache) >= 40:
            del _cache[next(iter(_cache))]
        _cache[token] = (now + TTL, chats, rep)
        _last = token
    return token


def take(token: str) -> Report | None:
    with _lock:
        item = _cache.pop(token, None)
    if item is None or item[0] < _time.monotonic():
        return None
    return item[2]


def _last_token() -> str:  # tests only
    return _last


def summary(r: Report) -> str:
    """The numbers in one paragraph: for the founder's note and the prospect's card."""
    parts = [f"Диалогов: {r.dialogues}, сообщений клиентов: {r.customer_messages}, из них в нерабочее время: {r.off_hours} ({r.off_hours_pct}%)."]
    if r.median_reply_minutes is not None:
        parts.append(f"Ответ в среднем через {_minutes(r.median_reply_minutes)}; дольше часа ждали {r.over_an_hour} из {r.answered}.")
    parts.append(f"Без ответа осталось: {r.unanswered}. Вопросов о цене: {r.price_questions}, из них ждали дольше часа или без ответа: "
                 f"{r.price_waited_over_an_hour}.")
    if r.first_day and r.last_day:
        parts.append(f"Период: {r.first_day:%d.%m.%Y}–{r.last_day:%d.%m.%Y}.")
    return " ".join(parts)


def _minutes(n: int) -> str:
    if n < 60:
        return f"{n} мин"
    h, m = divmod(n, 60)
    return f"{h} ч {m} мин" if m else f"{h} ч"

