"""Is the AI answering? Alerts for the founder when model calls keep failing.

When the Anthropic balance runs out, the key is wrong or the API is down, every business's AI answers
customers with the polite fallback and nobody on the platform side notices (eval run 41, 31 Oct 2026:
"Your credit balance is too low"). Every failed call is already stored as a lead of kind "error";
this module adds the reason (kept in memory, the API's text never goes to a business) and tells the
founder: a banner in the founder console, and a Telegram message when FOUNDER_BOT_TOKEN and
FOUNDER_CHAT_ID are set. When the model answers again after such an alert, the founder gets one more message:
how many customers were left without an answer and how many of them the AI answered later (joop/recovery.py).

The model is down (Status.down: the founder's alert, the dashboard's chip, the site's live chat) when
- ALERT_AFTER customers within WINDOW got the fallback and no call has succeeded since, or
- the last ALERT_AFTER calls that the provider itself failed all failed, one after another.
A server that only waited for customers never saw the second: on a quiet night three failed calls do not fall into
one half hour, nobody was alerted and «Сводка» said «ИИ отвечает» while every customer got the fallback (review of
#321–#327). So while the last call failed, the scheduler asks the model itself, once a tick (probe): the outage is
known within a few ticks of its first customer, and its end within one tick, whether or not anybody writes.
An answer that could not be used (BadOutput: the model's text was not JSON) is that chat's failure, not an outage:
it does not count, it only makes the server ask, and the model's answer to the server's own question settles it.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Lead

log = logging.getLogger(__name__)

WINDOW = timedelta(minutes=30)
ALERT_AFTER = 3  # failed calls: customers' within WINDOW, or the provider's own one after another
ALERT_EVERY = timedelta(hours=2)  # do not repeat the Telegram alert more often while it lasts
PROBE_EVERY = timedelta(minutes=5)  # while the last call failed: the server's own small call, at most this often
PROBE_QUIET = timedelta(minutes=1)  # no probe right after a call: a late answer tried in this tick was the probe
PING = 'Reply with the JSON {"reply": "ok"}.'

_lock = threading.Lock()
_recent: deque[tuple[datetime, str, bool]] = deque(maxlen=50)  # when, the reason, the provider's own failure
_unsure = False  # the last call failed, whatever the cause, and none has succeeded since
_in_a_row = 0  # calls the provider itself failed since the model last answered
_next_probe: datetime | None = None
_last_alert: datetime | None = None
_last_success: datetime | None = None  # the model answered (in memory, like the reasons)
_alert_open: datetime | None = None  # a "down" alert went out and its "back" message has not


_api = "Anthropic API"  # the provider in use (Runtime calls use_provider); alerts must name the right one


def use_provider(api_name: str) -> None:
    global _api
    _api = api_name


def check_hint(sentence: bool = False) -> str:
    """What the founder should look at, naming the provider this server uses; `sentence`: with a capital letter."""
    return f"{'Проверьте' if sentence else 'проверьте'} баланс и ключ {_api}"


def kind_of(exc: BaseException) -> str:
    """What failed. "output": the call went through and this one answer could not be used (BadOutput: not JSON,
    empty), which says nothing of the next customer's. Anything else is the provider's failure: its balance, key,
    limits, load, servers, the link to it, or a cause not named here."""
    from .agent.llm import BadOutput

    if isinstance(exc, BadOutput) or isinstance(exc.__cause__, BadOutput):
        return "output"
    cause = exc.__cause__ or exc
    text = f"{type(exc).__name__} {exc} {type(cause).__name__} {cause}".lower()
    if "credit balance" in text or "billing" in text:
        return "balance"
    if "authentication" in text or "invalid x-api-key" in text or "401" in text or ("api_key" in text and "not set" in text):
        return "key"
    if "ratelimit" in text or "rate_limit" in text or "429" in text:
        return "limit"
    if "overloaded" in text or "529" in text:
        return "overloaded"
    if "timeout" in text or "connect" in text:
        return "link"
    return "unknown"


def reason_of(exc: BaseException) -> str:
    """A short Russian reason for the founder, from the exception and its cause."""
    api = _api
    kind = kind_of(exc)
    if kind == "balance":
        return (f"закончился баланс {api} — пополните его в Plans & Billing" if api == "Anthropic API"
                else f"закончился баланс {api} — пополните его или включите оплату у поставщика")
    known = {"key": f"ключ {api} неверный или не задан", "limit": f"превышен лимит запросов {api}",
             "overloaded": f"{api} перегружен", "link": f"нет связи с {api}",
             "output": "ответ модели не удалось разобрать"}
    return known.get(kind) or f"ошибка вызова модели ({type(exc.__cause__ or exc).__name__})"


def record_failure(exc: BaseException, now: datetime, probe: bool = False) -> None:
    """A model call failed. `probe`: the server's own small call, which fails only when the model fails for all."""
    global _unsure, _in_a_row
    theirs = probe or kind_of(exc) != "output"
    with _lock:
        _recent.append((now, reason_of(exc), theirs))
        _unsure = True
        _in_a_row += theirs


def record_success(now: datetime) -> None:
    global _last_success, _unsure, _in_a_row
    with _lock:
        _unsure, _in_a_row = False, 0
        if _last_success is None or now > _last_success:
            _last_success = now


def last_reason(now: datetime) -> str:
    with _lock:
        recent = [r for t, r, _theirs in _recent if now - t <= WINDOW]
    return recent[-1] if recent else ""


def failing(now: datetime) -> bool:
    """The last ALERT_AFTER calls that the provider itself failed all failed, the latest within WINDOW, and no call
    has succeeded since. Kept in memory: after a restart the server knows of the customers' requests only."""
    with _lock:
        return _in_a_row >= ALERT_AFTER and bool(_recent) and now - _recent[-1][0] <= WINDOW


def probe(rt, now: datetime, down: bool = False) -> bool | None:
    """While the last call failed (or the customers' requests say the model is down): the server's own small call,
    at most once per PROBE_EVERY and never right after another call. True: the model answered; False: it did not;
    None: nothing to ask. The scheduler asks every tick, after the businesses' jobs."""
    global _next_probe
    with _lock:  # an unusable answer (BadOutput) tells nothing of the provider: only its own failures make a probe wait
        asked = next((t for t, _reason, theirs in reversed(_recent) if theirs), None)
        due = ((_unsure or down) and (asked is None or now - asked >= PROBE_QUIET)
               and (_next_probe is None or now >= _next_probe))
        if due:
            _next_probe = now + PROBE_EVERY
    if not due:
        return None
    try:
        rt.get_llm().respond(PING, [{"role": "user", "content": "ping"}])
    except Exception as exc:
        log.info("The model does not answer the server's own call: %s", type(exc).__name__)
        record_failure(exc, now, probe=True)
        return False
    record_success(now)
    return True


@dataclass
class Status:
    failures: int  # customers left with the fallback in the window, all businesses (their requests of kind "error")
    reason: str  # the latest known reason ("" after a restart)
    last_at: datetime | None
    last_success: datetime | None = None
    in_a_row: bool = False  # failing(): the provider's own failures, one after another
    output_only: bool = False  # every failure of the window is known, and each was one unusable answer (BadOutput)

    @property
    def recovered(self) -> bool:
        """The model answered after the last failure."""
        return bool(self.failures and self.last_success and self.last_at and self.last_success > self.last_at)

    @property
    def down(self) -> bool:
        return self.in_a_row or (self.failures >= ALERT_AFTER and not self.recovered and not self.output_only)

    @property
    def seen(self) -> str:
        """What the server saw, for the founder: customers left without an answer, or, at a quiet hour, only the
        server's own call (probe) failing."""
        from .lang import plural

        minutes = int(WINDOW.total_seconds() // 60)
        if self.failures:
            return f"За последние {minutes} минут не удалось ответить {self.failures} {plural(self.failures, 'раз', 'раза', 'раз')}"
        return f"За последние {minutes} минут клиенты не писали, но на проверочный вызов сервера модель не отвечает"


def status(session: Session, now: datetime) -> Status:
    since = now - WINDOW
    failures = session.exec(select(func.count()).select_from(Lead).where(Lead.kind == "error", Lead.created_at >= since)).one()
    last_at = session.exec(select(func.max(Lead.created_at)).where(Lead.kind == "error", Lead.created_at >= since)).one()
    with _lock:
        success = _last_success
        known = [theirs for t, _reason, theirs in _recent if t >= since]
    # after a restart the requests outnumber what the server remembers: then their cause is unknown, and they count
    output_only = bool(failures) and len(known) >= failures and not any(known)
    return Status(failures=failures, reason=last_reason(now), last_at=last_at, last_success=success,
                  in_a_row=failing(now), output_only=output_only)


def alert_text(st: Status) -> str:
    why = st.reason or f"причина неизвестна (сервер перезапускался) — {check_hint()}"
    return (f"Joop AI: ИИ не отвечает клиентам. {st.seen}. Причина: {why}. Пока это не исправлено, клиенты получают "
            "ответ «Извините, сейчас не получается ответить», а заявки уходят администраторам.")


def back_text(session: Session, since: datetime, back_at: datetime) -> str:
    """The "AI is back" message: what the outage left and what the recovery answered (joop/recovery.py)."""
    from .pilot import LATE
    from .timeutil import utc_to_local

    failed = session.exec(select(Lead).where(Lead.kind == "error", Lead.created_at >= since)).all()
    later = sum(1 for lead in failed if lead.closed_by == LATE)
    waiting = sum(1 for lead in failed if lead.status == "new")
    at = utc_to_local(back_at, "Asia/Bishkek").strftime("%H:%M")
    return (f"Joop AI: ИИ снова отвечает клиентам (с {at} по Бишкеку). За время сбоя без ответа остались "
            f"{len(failed)} сообщений: на {later} ИИ ответил сам с извинением за задержку, "
            f"{waiting} заявок ещё ждут сотрудников в панелях компаний.")


def tell_founder(rt, text: str) -> bool:
    """One Telegram message to the founder, when the founder bot is set up; False otherwise."""
    settings = rt.settings
    if not (getattr(settings, "founder_bot_token", "") and getattr(settings, "founder_chat_id", "")):
        return False
    return _send(rt, text)


def _send(rt, text: str) -> bool:
    from .channels.telegram import TelegramClient

    settings = rt.settings
    return TelegramClient(rt.http, settings.telegram_api_base, settings.founder_bot_token).send_text(settings.founder_chat_id, text)


def maybe_alert(session: Session, rt, now: datetime) -> bool:
    """Telegram for the founder: an alert when the AI is down (at most once per ALERT_EVERY), and one message when
    it answers again after such an alert. Runs after the businesses' jobs, so late answers are already counted."""
    global _last_alert, _alert_open
    settings = rt.settings
    token, chat = getattr(settings, "founder_bot_token", ""), getattr(settings, "founder_chat_id", "")
    if not (token and chat):
        return False
    st = status(session, now)
    with _lock:
        opened, success = _alert_open, _last_success
    if not st.down:
        if opened is None or success is None or success <= opened:
            return False
        with _lock:
            _alert_open = None
            _last_alert = None  # a new outage gets its own alert at once
        ok = _send(rt, back_text(session, opened - WINDOW, success))
        if not ok:
            log.warning("Founder message that the AI is back was not delivered")
        return ok
    with _lock:
        if _last_alert and now - _last_alert < ALERT_EVERY:
            return False
        _last_alert = now
        _alert_open = _alert_open or now
    ok = _send(rt, alert_text(st))
    if not ok:
        log.warning("Founder alert about the AI was not delivered")
    return ok


def reset() -> None:
    """For tests."""
    global _last_alert, _last_success, _alert_open, _unsure, _in_a_row, _next_probe
    with _lock:
        _recent.clear()
        _last_alert = None
        _last_success = None
        _alert_open = None
        _unsure, _in_a_row, _next_probe = False, 0, None
