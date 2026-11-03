"""Is the AI answering? Alerts for the founder when model calls keep failing.

When the Anthropic balance runs out, the key is wrong or the API is down, every business's AI answers
customers with the polite fallback and nobody on the platform side notices (eval run 41, 31 Oct 2026:
"Your credit balance is too low"). Every failed call is already stored as a lead of kind "error";
this module adds the reason (kept in memory, the API's text never goes to a business) and tells the
founder: a banner in the founder console, and a Telegram message when FOUNDER_BOT_TOKEN and
FOUNDER_CHAT_ID are set. When the model answers again after such an alert, the founder gets one more message:
how many customers were left without an answer and how many of them the AI answered later (joop/recovery.py).
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
ALERT_AFTER = 3  # failed calls within WINDOW
ALERT_EVERY = timedelta(hours=2)  # do not repeat the Telegram alert more often while it lasts

_lock = threading.Lock()
_recent: deque[tuple[datetime, str]] = deque(maxlen=50)
_last_alert: datetime | None = None
_last_success: datetime | None = None  # the model answered (in memory, like the reasons)
_alert_open: datetime | None = None  # a "down" alert went out and its "back" message has not


def reason_of(exc: BaseException) -> str:
    """A short Russian reason for the founder, from the exception and its cause."""
    cause = exc.__cause__ or exc
    text = f"{type(exc).__name__} {exc} {type(cause).__name__} {cause}".lower()
    if "credit balance" in text or "billing" in text:
        return "закончился баланс Anthropic API — пополните его в Plans & Billing"
    if "authentication" in text or "invalid x-api-key" in text or "401" in text or ("api_key" in text and "not set" in text):
        return "ключ Anthropic API неверный или не задан"
    if "ratelimit" in text or "rate_limit" in text or "429" in text:
        return "превышен лимит запросов Anthropic API"
    if "overloaded" in text or "529" in text:
        return "Anthropic API перегружен"
    if "timeout" in text or "connect" in text:
        return "нет связи с Anthropic API"
    return f"ошибка вызова модели ({type(cause).__name__})"


def record_failure(exc: BaseException, now: datetime) -> None:
    with _lock:
        _recent.append((now, reason_of(exc)))


def record_success(now: datetime) -> None:
    global _last_success
    with _lock:
        if _last_success is None or now > _last_success:
            _last_success = now


def last_reason(now: datetime) -> str:
    with _lock:
        recent = [r for t, r in _recent if now - t <= WINDOW]
    return recent[-1] if recent else ""


@dataclass
class Status:
    failures: int  # failed model calls in the window, all businesses
    reason: str  # the latest known reason ("" after a restart)
    last_at: datetime | None
    last_success: datetime | None = None

    @property
    def recovered(self) -> bool:
        """The model answered after the last failure."""
        return bool(self.failures and self.last_success and self.last_at and self.last_success > self.last_at)

    @property
    def down(self) -> bool:
        return self.failures >= ALERT_AFTER and not self.recovered


def status(session: Session, now: datetime) -> Status:
    since = now - WINDOW
    failures = session.exec(select(func.count()).select_from(Lead).where(Lead.kind == "error", Lead.created_at >= since)).one()
    last_at = session.exec(select(func.max(Lead.created_at)).where(Lead.kind == "error", Lead.created_at >= since)).one()
    with _lock:
        success = _last_success
    return Status(failures=failures, reason=last_reason(now), last_at=last_at, last_success=success)


def alert_text(st: Status) -> str:
    why = st.reason or "причина неизвестна (сервер перезапускался) — проверьте баланс и ключ Anthropic"
    return (f"Joop AI: ИИ не отвечает клиентам. За последние {int(WINDOW.total_seconds() // 60)} минут "
            f"не удалось ответить {st.failures} раз. Причина: {why}. Пока это не исправлено, клиенты получают "
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
    global _last_alert, _last_success, _alert_open
    with _lock:
        _recent.clear()
        _last_alert = None
        _last_success = None
        _alert_open = None
