"""What the customer reads after a booking, an order or a room or hall booking: the facts come from the code.

The model proposes the action and writes the reply; the code checks the action and saves exactly what it checked.
The reply is still the model's words, and they can name another time, date or sum («записала на 13:00» for the
12:00 slot, «с вас 1 200 сом» for an 820-som order). So, after the language guard and before anything else is
added (the AI introduction, prepayment, questions):

- a sentence that claims the action («записала», «забронировала», «итого», «жазылдыңыз», …) and names a time, date
  or sum the saved action does not have is removed — only that sentence: an address, a question or a working-hours
  remark the model wrote stays;
- a line written from the saved action follows: «Ваша запись: Чт 05.11 12:00, Бакыт Осмонов.», «Ваш заказ:
  2 × Плов. Сумма заказа: 820 сом.», «Бронь: «Семейный номер», 25.11.2026–28.11.2026, гостей: 2.» — in Kyrgyz
  when the reply is Kyrgyz (KY wording: проверить носителю). For a booking the line is left out when a claim
  sentence already names the booked date and time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from .confirm import fmt_slot_ky
from .models import Booking, OrderLine, Stay
from .timeutil import fmt_slot

CLAIM = re.compile(
    r"запис(ал|ыва|ан|ь)|заброниров|бронь|брониру|оформ(ил|лен)|принят|ждём вас|ждем вас|ждем|ждём|приходите|"
    r"итого|всего|сумм|с вас|к оплате|стоимост|"
    r"жаз(ып|ылд|дым|дык|ылуу)|брондо|кабыл ал|күтөбүз|келиңиз|баары|жалпы|төлөй", re.I)
TOTAL_WORD = re.compile(r"итог|всего|к оплате|с вас|жалпы|баары|бардыгы", re.I)  # «итого 700» names the whole order
_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_CLOCK = re.compile(r"(?<![\d:.])([01]?\d|2[0-3])([:.])([0-5]\d)(?![\d:]|\.\d)")
_DAY_MONTH = re.compile(r"(?<![\d.,])(\d{1,2})\.(\d{2})(?:\.(?:\d{4}|\d{2}))?(?![\d])")
_DAY_RANGE = re.compile(r"(?<![\d.,])(\d{1,2})\s*(?:по|до|-|–|—)\s*\d{1,2}\.(\d{2})(?![\d])")
_GAP = "[    ]"
_SUM = re.compile(rf"(?<![\d.,])(\d{{1,3}}(?:{_GAP}\d{{3}})+|\d+)(?:[.,]\d{{1,2}})?{_GAP}*(?:сом\w*|с|c|som|kgs)(?![a-zа-яё])", re.I)

BOOKED_RU, BOOKED_KY = "Ваша запись: {when}, {who}.", "Жазылдыңыз: {when}, {who}."
DONE_BOOKING_RU, DONE_BOOKING_KY = "Записала вас.", "Жазып койдум."
DONE_ORDER_RU, DONE_ORDER_KY = "Оформила заказ.", "Буйрутмаңызды кабыл алдым."
DONE_STAY_RU, DONE_STAY_KY = "Забронировала.", "Брондоп койдум."


def sentences(text: str) -> list[str]:
    return [x for x in _SPLIT.split(text or "") if x.strip()]


def clock_times(text: str) -> set[str]:
    """"12:00", "9.30" → {"12:00", "09:30"}; "12.11" is a date (a minute value up to 12 after a dot reads as a month)."""
    return {f"{int(h):02d}:{m}" for h, sep, m in _CLOCK.findall(text) if sep == ":" or m == "00" or int(m) > 12}


def day_months(text: str) -> set[tuple[int, int]]:
    """Day-month dates named in the text: 05.11, 05.11.2026, and the first day of «с 10 по 13.12»; «2.5 км» is none."""
    named = {(int(d), int(m)) for d, m in _DAY_MONTH.findall(text)}
    named |= {(int(d), int(m)) for d, m in _DAY_RANGE.findall(text)}
    return {(d, m) for d, m in named if 1 <= d <= 31 and 1 <= m <= 12}


def sums(text: str) -> set[int]:
    return {int(re.sub(_GAP, "", x)) for x in _SUM.findall(text)}


def _keep(reply: str, wrong, done: str) -> tuple[list[str], list[str]]:
    """(the sentences kept, the claim sentences kept) after removing claim sentences `wrong` rejects. When every claim
    went, `done` («Записала вас.») opens the reply so it still says what happened."""
    kept, claims, removed = [], [], False
    for sentence in sentences(reply):
        if CLAIM.search(sentence):
            if wrong(sentence):
                removed = True
                continue
            claims.append(sentence)
        kept.append(sentence)
    if removed and not claims or not kept:
        kept.insert(0, done)
    return kept, claims


def _join(kept: list[str], line: str) -> str:
    head = " ".join(kept).strip()
    return f"{head}\n{line}" if line else head


def with_booking(reply: str, booking: Booking, kyrgyz: bool) -> str:
    when = fmt_slot_ky(booking.start) if kyrgyz else fmt_slot(booking.start)
    line = (BOOKED_KY if kyrgyz else BOOKED_RU).format(when=when, who=booking.staff_name)
    booked_time, booked_day = f"{booking.start:%H:%M}", (booking.start.day, booking.start.month)

    def wrong(sentence: str) -> bool:
        times, days = clock_times(sentence), day_months(sentence)
        return bool(times and booked_time not in times) or bool(days and days != {booked_day})

    kept, claims = _keep(reply, wrong, DONE_BOOKING_KY if kyrgyz else DONE_BOOKING_RU)
    exact = any(booked_time in clock_times(c) and booked_day in day_months(c) for c in claims)
    return _join(kept, "" if exact else line)


@dataclass
class OrderFacts:
    lines: list[OrderLine]
    total: int | None
    fee: int
    known: set[int]  # sums the reply may name: the total, the items' total, the fee, prices, subtotals, thresholds
    names_ky: dict[int, str]  # item id → its Kyrgyz name, for a Kyrgyz chat


def order_facts(lines: list[OrderLine], total: int | None, fee: int, thresholds: tuple[int, ...],
                names_ky: dict[int, str] | None = None) -> OrderFacts:
    known = {x for x in (total, fee, *thresholds) if x}
    if total is not None:
        known.add(total - fee)
    for r in lines:
        if r.unit_price is not None:
            known |= {r.unit_price, r.unit_price * r.quantity}
    return OrderFacts(lines, total, fee, known, names_ky or {})


def order_line(facts: OrderFacts, kyrgyz: bool) -> str:
    items = ", ".join(f"{r.quantity} × {(facts.names_ky.get(r.item_id) if kyrgyz else None) or r.name}" for r in facts.lines)
    som = lambda v: f"{v:,} сом".replace(",", " ")  # noqa: E731
    if kyrgyz:
        if facts.total is None:
            money = "Так сумманы администратор тактайт."
        elif facts.fee:
            money = f"Жалпы суммасы: {som(facts.total)}, анын ичинде жеткирүү {som(facts.fee)}."
        else:
            money = f"Жалпы суммасы: {som(facts.total)}."
        return f"Буйрутмаңыз: {items}. {money}"
    if facts.total is None:
        money = "Точную сумму подтвердит администратор."
    elif facts.fee:
        money = f"Сумма заказа: {som(facts.total)}, включая доставку {som(facts.fee)}."
    else:
        money = f"Сумма заказа: {som(facts.total)}."
    return f"Ваш заказ: {items}. {money}"


def with_order(reply: str, facts: OrderFacts, kyrgyz: bool) -> str:
    """A claim sentence with a sum the order does not have goes, and one with a total word («итого», «жалпы») whose sums
    leave out the order's total (700 for the food of an 850 order with delivery); «сдача с 1000 или 5000?» is not a claim
    and stays."""
    def wrong(sentence: str) -> bool:
        named = sums(sentence)
        total_word = bool(named and facts.total is not None and TOTAL_WORD.search(sentence) and facts.total not in named)
        return bool(named - facts.known) or total_word

    kept, _ = _keep(reply, wrong, DONE_ORDER_KY if kyrgyz else DONE_ORDER_RU)
    return _join(kept, order_line(facts, kyrgyz))


def stay_line(stay: Stay, hall: bool, with_guests: bool, kyrgyz: bool) -> str:
    dates = f"{stay.check_in:%d.%m.%Y}" if hall else f"{stay.check_in:%d.%m.%Y}–{stay.check_out:%d.%m.%Y}"
    if kyrgyz:
        return f"Брон: «{stay.room_name}», {dates}" + (f", конок саны: {stay.guests}." if with_guests else ".")
    return f"Бронь: «{stay.room_name}», {dates}" + (f", гостей: {stay.guests}." if with_guests else ".")


def with_stay(reply: str, stay: Stay, hall: bool, with_guests: bool, kyrgyz: bool, fixed: str = "") -> str:
    """For a hotel or a car the days are check-in and check-out; for a hall, the one day. `fixed` is the niche's own
    full confirmation (dates, guests, who calls about payment): used whole when nothing of the reply is left."""
    allowed = {(stay.check_in.day, stay.check_in.month)}
    if not hall:
        allowed.add((stay.check_out.day, stay.check_out.month))
        allowed |= {(d.day, d.month) for d in _days(stay.check_in, stay.check_out)}

    done = DONE_STAY_KY if kyrgyz else DONE_STAY_RU
    kept, claims = _keep(reply, lambda sentence: bool(day_months(sentence) - allowed), done)
    if kept == [done] and fixed and not kyrgyz:
        return fixed  # nothing of the reply is left: the niche's own full confirmation, which already has the dates
    return _join(kept, stay_line(stay, hall, with_guests, kyrgyz))


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]

