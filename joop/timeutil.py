"""Time helpers.

Convention used across the project:
- columns ending in ``_at`` hold naive UTC datetimes;
- slot and booking ``start`` hold naive local time of the business (its timezone setting).
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Bishkek"
WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def utc_to_local(dt_utc: datetime, tz_name: str | None) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(get_tz(tz_name)).replace(tzinfo=None)


def local_to_utc(dt_local: datetime, tz_name: str | None) -> datetime:
    return dt_local.replace(tzinfo=get_tz(tz_name)).astimezone(timezone.utc).replace(tzinfo=None)


def local_now(tz_name: str | None, now_utc: datetime | None = None) -> datetime:
    return utc_to_local(now_utc or utcnow(), tz_name)


def parse_hhmm(value: str | None, default: time | None = None) -> time | None:
    """Parse '9', '09:00', '9.30' into a time. Returns `default` when the value is unusable."""
    s = (value or "").strip().replace(".", ":")
    if not s:
        return default
    parts = s.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        return time(hour, minute)
    except (ValueError, IndexError):
        return default


def parse_days_off(value: str | None) -> set[int]:
    """'6,7' -> {6, 7}. ISO weekdays: 1 = Monday ... 7 = Sunday."""
    days: set[int] = set()
    for part in (value or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 7:
            days.add(int(part))
    return days


def is_off_hours(local_dt: datetime, work_start: str, work_end: str, days_off: str) -> bool:
    """True when the business is closed at this local time (day off or outside working hours)."""
    if local_dt.isoweekday() in parse_days_off(days_off):
        return True
    start = parse_hhmm(work_start, time(9, 0))
    end = parse_hhmm(work_end, time(19, 0))
    current = local_dt.time()
    return not (start <= current < end)


def fmt_slot(dt: datetime) -> str:
    """'Вт 04.11 10:00'"""
    return f"{WEEKDAYS_SHORT[dt.weekday()]} {dt:%d.%m %H:%M}"


def fmt_dt(dt: datetime | None) -> str:
    return "" if dt is None else f"{dt:%d.%m.%Y %H:%M}"


def fmt_date_long(dt: datetime) -> str:
    """'вторник, 04.11.2026'"""
    return f"{WEEKDAYS_FULL[dt.weekday()]}, {dt:%d.%m.%Y}"
