"""Stays: hotel nights, or the date of a banquet hall, booked atomically.

A room type is a resource (Staff): `group_size` = how many such rooms, `capacity` = guests per room.
Each booked night of each room is a RoomNight row with a unique (room type, night, unit) key, so two
customers can never get the last room for the same night, even at the same moment.

A pack with `stay_by: day` (banquet halls) books single dates: a hall is a "room type" of one unit, an
event is one RoomNight on its date, and the customer-facing words speak of halls and dates, not nights.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

from .models import Business, Conversation, Message, RoomNight, Staff, Stay
from .niches import Pack, get_pack

MAX_NIGHTS = 30
MAX_AHEAD_DAYS = 365
ROLL_AFTER_DAYS = 14  # a date this far in the past, given without a year, means next year
_YEAR = re.compile(r"\b20\d\d\b")


def room_types(session: Session, business_id: int, hidden: frozenset[int] = frozenset()) -> list[Staff]:
    """Active room types; `hidden` are sign-up example rooms a real guest must not be offered (samples.Hidden.staff)."""
    return [r for r in session.exec(select(Staff).where(Staff.business_id == business_id, Staff.active == True)  # noqa: E712
                                    .order_by(Staff.id)).all() if r.id not in hidden]


def rooms_of(room: Staff) -> int:
    return max(1, room.group_size)


def nights(check_in: date, check_out: date) -> list[date]:
    return [check_in + timedelta(days=i) for i in range((check_out - check_in).days)]


def taken_units(session: Session, room_id: int, night: date) -> set[int]:
    return set(session.exec(select(RoomNight.unit).where(RoomNight.staff_id == room_id, RoomNight.night == night)).all())


def free_rooms(session: Session, room: Staff, check_in: date, check_out: date, units: int | None = None) -> int:
    total = rooms_of(room) if units is None else units
    return min((total - len(taken_units(session, room.id, n)) for n in nights(check_in, check_out)), default=0)


HALL_UNITS = 1  # a banquet hall is one hall on a date, whatever room count it kept from another niche


def by_day(business: Business) -> bool:
    return get_pack(business.niche).by_day


def taken_dates(session: Session, room: Staff, start: date, days: int, units: int | None = None) -> list[date]:
    """Dates from `start` on, within `days`, on which every unit of this room type is booked."""
    rows = session.exec(select(RoomNight.night).where(RoomNight.staff_id == room.id, RoomNight.night >= start,
                                                      RoomNight.night < start + timedelta(days=days))).all()
    counts: dict[date, int] = {}
    for n in rows:
        counts[n] = counts.get(n, 0) + 1
    total = rooms_of(room) if units is None else units
    return sorted(d for d, c in counts.items() if c >= total)


def parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


def _next_year(d: date) -> date:
    return d.replace(year=d.year + 1) if not (d.month == 2 and d.day == 29) else date(d.year + 1, 3, 1)


def roll_year(session: Session, conv: Conversation, check_in: date, check_out: date, today: date) -> tuple[date, date]:
    """"С 1 по 4 августа" in October means next August. The model sometimes writes this year; the code fixes it
    when the date is clearly past and the customer named no year."""
    if check_in >= today - timedelta(days=ROLL_AFTER_DAYS):
        return check_in, check_out
    texts = session.exec(select(Message.text).where(Message.conversation_id == conv.id, Message.role == "customer")
                         .order_by(Message.id.desc()).limit(3)).all()
    if any(_YEAR.search(t or "") for t in texts):
        return check_in, check_out  # the customer wrote a year: do not guess
    return _next_year(check_in), _next_year(check_out)


def _fmt(d: date) -> str:
    return f"{d:%d.%m.%Y}"


@dataclass
class StayResult:
    reply: str
    stay: Stay | None = None


def book(session: Session, business: Business, conv: Conversation, data: dict, reply: str, today: date, now_utc: datetime,
         off: bool, channel: str, name: str, phone: str, hidden: frozenset[int] = frozenset()) -> StayResult:
    day = by_day(business)
    check_in, check_out = parse_day(data.get("check_in", "")), parse_day(data.get("check_out", ""))
    if day and check_in:
        check_out = check_in + timedelta(days=1)  # one event = one date, whatever the model wrote as check_out
    if not check_in or not check_out or check_out <= check_in:
        return StayResult("Уточните, пожалуйста, дату мероприятия." if day else "Уточните, пожалуйста, даты заезда и выезда.")
    asked_year = check_in.year
    check_in, check_out = roll_year(session, conv, check_in, check_out, today)
    if check_in < today or check_in > today + timedelta(days=MAX_AHEAD_DAYS):
        return StayResult(f"Бронируем с {_fmt(today)} и не дальше чем на год вперёд. Уточните, пожалуйста, "
                          + ("дату." if day else "даты."))
    if day:
        return _book_date(session, business, conv, data, reply, check_in, asked_year, now_utc, off, channel, name, phone, hidden)
    if (check_out - check_in).days > MAX_NIGHTS:
        return StayResult(f"Онлайн можно забронировать до {MAX_NIGHTS} ночей; для долгого проживания администратор свяжется с вами.")
    room = session.get(Staff, data.get("room_id")) if data.get("room_id") else None
    if room is None or room.business_id != business.id or not room.active or room.id in hidden:
        return StayResult("Какой номер вам подходит? " + _options(session, business, check_in, check_out, data.get("guests") or 1, hidden))
    guests = max(1, int(data.get("guests") or 1))
    if room.capacity and guests > room.capacity:
        return StayResult(f"«{room.name}» рассчитан на {room.capacity} гостей. " + _options(session, business, check_in, check_out, guests, hidden))
    if free_rooms(session, room, check_in, check_out) <= 0:
        return StayResult(f"На {_fmt(check_in)}–{_fmt(check_out)} «{room.name}» уже занят. "
                          + _options(session, business, check_in, check_out, guests, hidden))
    stay = Stay(business_id=business.id, staff_id=room.id, room_name=room.name, check_in=check_in, check_out=check_out,
                guests=guests, customer_name=name, customer_phone=phone, conversation_id=conv.id, channel=channel,
                chat_id=conv.chat_id, created_off_hours=off, created_at=now_utc)
    try:
        with session.begin_nested():
            session.add(stay)
            session.flush()
            for n in nights(check_in, check_out):
                taken = taken_units(session, room.id, n)
                unit = next(u for u in range(rooms_of(room)) if u not in taken)
                session.add(RoomNight(business_id=business.id, staff_id=room.id, stay_id=stay.id, night=n, unit=unit))
            session.flush()
    except (IntegrityError, StopIteration):
        return StayResult(f"Извините, «{room.name}» на эти даты только что заняли. "
                          + _options(session, business, check_in, check_out, guests, hidden))
    if check_in.year != asked_year and str(asked_year) in reply:  # the model's confirmation names the wrong year
        reply = (f"Забронировала «{room.name}» на {_fmt(check_in)}–{_fmt(check_out)}, гостей: {guests}. "
                 "Администратор свяжется с вами насчёт оплаты.")
    return StayResult(reply, stay)


def _book_date(session: Session, business: Business, conv: Conversation, data: dict, reply: str, when: date, asked_year: int,
               now_utc: datetime, off: bool, channel: str, name: str, phone: str, hidden: frozenset[int]) -> StayResult:
    """A banquet hall: one date, one hall, the guests within its capacity."""
    guests = max(1, int(data.get("guests") or 1))
    room = session.get(Staff, data.get("room_id")) if data.get("room_id") else None
    if room is None or room.business_id != business.id or not room.active or room.id in hidden:
        return StayResult("Какой зал вам подходит? " + _hall_options(session, business, when, guests, hidden))
    if room.capacity and guests > room.capacity:
        return StayResult(f"«{room.name}» вмещает до {room.capacity} гостей. " + _hall_options(session, business, when, guests, hidden))
    if free_rooms(session, room, when, when + timedelta(days=1), HALL_UNITS) <= 0:
        return StayResult(f"На {_fmt(when)} «{room.name}» уже занят. " + _hall_options(session, business, when, guests, hidden))
    stay = Stay(business_id=business.id, staff_id=room.id, room_name=room.name, check_in=when, check_out=when + timedelta(days=1),
                guests=guests, customer_name=name, customer_phone=phone, conversation_id=conv.id, channel=channel,
                chat_id=conv.chat_id, created_off_hours=off, created_at=now_utc)
    try:
        with session.begin_nested():
            session.add(stay)
            session.flush()
            session.add(RoomNight(business_id=business.id, staff_id=room.id, stay_id=stay.id, night=when, unit=0))
            session.flush()
    except IntegrityError:
        return StayResult(f"Извините, «{room.name}» на {_fmt(when)} только что заняли. "
                          + _hall_options(session, business, when, guests, hidden))
    if when.year != asked_year and str(asked_year) in reply:  # the model's confirmation names the wrong year
        reply = (f"Предварительно забронировала «{room.name}» на {_fmt(when)}, гостей: {guests}. "
                 "Менеджер свяжется с вами насчёт предоплаты и меню.")
    return StayResult(reply, stay)


def _hall_options(session: Session, business: Business, when: date, guests: int, hidden: frozenset[int] = frozenset()) -> str:
    fits = [r for r in room_types(session, business.id, hidden)
            if (not r.capacity or r.capacity >= guests) and free_rooms(session, r, when, when + timedelta(days=1), HALL_UNITS) > 0]
    if not fits:
        return (f"На {_fmt(when)} свободного зала на {guests} гостей нет. "
                "Оставьте телефон — менеджер предложит другую дату или вариант.")
    return f"Свободно на {_fmt(when)}: " + "; ".join(f"{r.name} (до {r.capacity} гостей)" if r.capacity else r.name
                                                   for r in fits[:4]) + ". Какой выбираете?"


def _options(session: Session, business: Business, check_in: date, check_out: date, guests: int,
             hidden: frozenset[int] = frozenset()) -> str:
    fits = [r for r in room_types(session, business.id, hidden)
            if (not r.capacity or r.capacity >= guests) and free_rooms(session, r, check_in, check_out) > 0]
    if not fits:
        return f"На {_fmt(check_in)}–{_fmt(check_out)} свободных номеров нет. Оставьте телефон — администратор предложит варианты."
    return f"Свободно на {_fmt(check_in)}–{_fmt(check_out)}: " + "; ".join(r.name for r in fits[:4]) + ". Какой выбираете?"


def cancel(session: Session, stay: Stay) -> None:
    stay.status = "cancelled"
    session.add(stay)
    session.exec(delete(RoomNight).where(RoomNight.stay_id == stay.id))


def occupancy(session: Session, business_id: int, start: date, days: int,
              units: int | None = None) -> list[tuple[Staff, list[tuple[date, int, int]]]]:
    """For the panel: per room type, each day with (night, taken, total); `units` overrides the room count (halls)."""
    out = []
    for room in room_types(session, business_id):
        rows = session.exec(select(RoomNight.night).where(RoomNight.staff_id == room.id, RoomNight.night >= start,
                                                          RoomNight.night < start + timedelta(days=days))).all()
        counts: dict[date, int] = {}
        for n in rows:
            counts[n] = counts.get(n, 0) + 1
        out.append((room, [(start + timedelta(days=i), counts.get(start + timedelta(days=i), 0),
                                rooms_of(room) if units is None else units) for i in range(days)]))
    return out


SHOWN_DATES = 40  # taken dates of one hall listed in the prompt


def prompt_lines(session: Session, business: Business, today: date, hidden: frozenset[int] = frozenset()) -> list[str]:
    if by_day(business):
        return _hall_lines(session, business, today, hidden)
    lines = ["", f"Номера (номер в квадратных скобках — room_id; сегодня {today:%Y-%m-%d}):"]
    rooms = room_types(session, business.id, hidden)
    for r in rooms:
        cap = f", до {r.capacity} гостей" if r.capacity else ""
        lines.append(f"- [{r.id}] {r.name}{cap}, номеров такого типа: {rooms_of(r)}")
    if not rooms:
        lines.append("- номеров в данных нет: бронь не оформляй, возьми телефон и передай администратору.")
    return lines


def _hall_lines(session: Session, business: Business, today: date, hidden: frozenset[int]) -> list[str]:
    lines = ["", f"Залы (номер в квадратных скобках — room_id; сегодня {today:%Y-%m-%d}; занятые даты — на год вперёд):"]
    halls = room_types(session, business.id, hidden)
    for r in halls:
        cap = f", до {r.capacity} гостей" if r.capacity else ""
        taken = taken_dates(session, r, today, MAX_AHEAD_DAYS + 1, HALL_UNITS)
        if not taken:
            busy = "занятых дат нет"
        else:
            busy = "занятые даты: " + ", ".join(_fmt(d) for d in taken[:SHOWN_DATES])
            if len(taken) > SHOWN_DATES:
                busy += f" и ещё {len(taken) - SHOWN_DATES} (позже {_fmt(taken[SHOWN_DATES - 1])})"
        lines.append(f"- [{r.id}] {r.name}{cap}; {busy}")
    if not halls:
        lines.append("- залов в данных нет: бронь не оформляй, возьми телефон и передай менеджеру.")
    return lines


STAY_FORMAT = ('"stay": null или {"room_id": номер из списка номеров, "check_in": "ГГГГ-ММ-ДД", "check_out": "ГГГГ-ММ-ДД", '
               '"guests": число гостей, "name": "имя", "phone": "телефон"}')
STAY_RULE = ("Бронь номера: узнай даты заезда и выезда, число гостей, номер, имя и телефон; спрашивай только то, чего не хватает. "
             "Когда всё есть, заполни stay (даты в формате ГГГГ-ММ-ДД; если месяц в этом году уже прошёл — следующий год). "
             "Наличие проверит система: если номер свободен, бронь сохранится, иначе система сама предложит варианты. "
             "В reply подтверди номер и даты так, как в stay, и напиши, что администратор свяжется насчёт оплаты.")
HALL_FORMAT = ('"stay": null или {"room_id": номер зала из списка залов, "check_in": "ГГГГ-ММ-ДД" — дата мероприятия, '
               '"check_out": "" (пустая строка), "guests": число гостей, "name": "имя", "phone": "телефон"}')
HALL_RULE = ("Бронь зала: узнай дату мероприятия, число гостей, зал, имя и телефон; спрашивай только то, чего не хватает. "
             "Свободна ли дата, смотри по занятым датам зала; если зал занят или мал для гостей, предложи другой зал или дату. "
             "Когда всё есть, заполни stay (дата в формате ГГГГ-ММ-ДД; если месяц в этом году уже прошёл — следующий год). "
             "Наличие проверит система: если зал свободен, бронь сохранится, иначе система сама предложит варианты. "
             "В reply подтверди зал и дату так, как в stay: бронь предварительная, менеджер свяжется насчёт предоплаты и меню.")


def stay_format(pack: Pack) -> str:
    return HALL_FORMAT if pack.by_day else STAY_FORMAT


def rule(business: Business) -> str:
    return HALL_RULE if by_day(business) else STAY_RULE
