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

CLAIM = re.compile(r"запис(ал|ан)|заброниров|бронь|оформ(ил|лен)|приня(л|т)|"
                   r"жаз(ып|ылд|дым|дык)|брондо|кабыл ал", re.I)  # the action itself, not «ждём вас» or «работаем»
TOTAL_WORD = re.compile(r"итог|всего|к оплате|с вас|жалпы|баары|бардыгы", re.I)  # «итого 700» names the whole order
_ABBR = re.compile(r"(?:^|[\s(])(?:г|гг|ул|пр|просп|пер|д|кв|мкр|корп|стр|им|т\.е|т\.к|т\.д|т\.п|янв|фев|февр|мар|апр|"
                   r"авг|сен|сент|окт|нояб|дек|ч|мин|тел|напр|ок)\.$", re.I)
_CLOCK = re.compile(r"(?<![\d:.])([01]?\d|2[0-3])([:.])([0-5]\d)(?![\d:]|\.\d)")
_DAY_MONTH = re.compile(r"(?<![\d.,])(\d{1,2})\.(\d{2})(?:\.(?:\d{4}|\d{2}))?(?![\d])")
_DAY_RANGE = re.compile(r"(?<![\d.,])(\d{1,2})\s*(?:по|до|-|–|—)\s*\d{1,2}\.(\d{2})(?![\d])")
_MONTHS = ("янв", "фев", "мар", "апр", "ма", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
_DAY_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*-?\s*(янв|фев|мар|апр|ма[йяе]|июн|июл|авг|сен|окт|ноя|дек)", re.I)
_RELATIVE = {r"\bсегодня\b|\bбүгүн": 0, r"\bзавтра\b|\bэртең": 1, r"\bпослезавтра\b|\bбүрсүгүнү": 2}
_WEEKDAYS = (r"понедельник|дүйшөмбү", r"вторник|шейшемби", r"сред[ау]\b|шаршемби", r"четверг|бейшемби",
             r"пятниц", r"суббот|ишемби", r"воскресень|жекшемби")
_GAP = "[ \u00a0\u202f\u2009]"
_SUM = re.compile(rf"(?<![\d.,:])(\d{{1,3}}(?:{_GAP}\d{{3}})+|\d+)(?:[.,]\d{{1,2}})?{_GAP}*(?:сом\w*|som|kgs)(?![a-zа-яё])", re.I)
_SUM_C = re.compile(r"(?<![\d.,:])(\d{2,})[сc](?![a-zа-яё\d])", re.I)  # «1200с», never «18:00 с курьером»
_QTY = re.compile(r"(?<![\d.,:])(\d{1,3})\s*(?:×|x|х|шт\.?)?\s*([а-яёa-z]{3,})|([а-яёa-z]{3,})\s*(?:×|x|х)\s*(\d{1,3})(?![\d])", re.I)

BOOKED_RU, BOOKED_KY = "Ваша запись: {when}, {who}.", "Жазылдыңыз: {when}, {who}."
DONE_BOOKING_RU, DONE_BOOKING_KY = "Записала вас.", "Жазып койдум."
DONE_ORDER_RU, DONE_ORDER_KY = "Оформила заказ.", "Буйрутмаңызды кабыл алдым."
DONE_STAY_RU, DONE_STAY_KY = "Забронировала.", "Брондоп койдум."


def _spans(line: str) -> list[tuple[int, int]]:
    """Sentences of one line: a stop followed by a capital or the end, not after «ул.», «г.», «нояб.» or in «2.5»."""
    out, start, i, n = [], 0, 0, len(line)
    while i < n:
        if line[i] in ".!?…":
            j = i + 1
            while j < n and line[j] in ".!?…":
                j += 1
            k = j
            while k < n and line[k] in " \t":
                k += 1
            ends = k >= n or (k > j and (line[k].isupper() or line[k] in "«\"(-–—"))
            if line[i] == "." and k < n and _ABBR.search(line[start:i + 1]):
                ends = False
            if ends:
                out.append((start, j))
                start = i = k
                continue
        i += 1
    if start < n:
        out.append((start, n))
    return [(a, b) for a, b in out if line[a:b].strip()]


def sentences(text: str) -> list[str]:
    return [line[a:b].strip() for line in (text or "").split("\n") for a, b in _spans(line)]


def clock_times(text: str) -> set[str]:
    """"12:00", "9.30" → {"12:00", "09:30"}; "12.11" is a date (a minute value up to 12 after a dot reads as a month)."""
    return {f"{int(h):02d}:{m}" for h, sep, m in _CLOCK.findall(text) if sep == ":" or m == "00" or int(m) > 12}


def day_months(text: str) -> set[tuple[int, int]]:
    """Day-month dates named in the text: 05.11, 05.11.2026, the first day of «с 10 по 13.12», «6 ноября», «5-ноябрда»;
    «2.5 км» is none."""
    named = {(int(d), int(m)) for d, m in _DAY_MONTH.findall(text)}
    named |= {(int(d), int(m)) for d, m in _DAY_RANGE.findall(text)}
    named |= {(int(d), next(i for i, x in enumerate(_MONTHS, 1) if m.lower().startswith(x))) for d, m in _DAY_WORD.findall(text)}
    return {(d, m) for d, m in named if 1 <= d <= 31 and 1 <= m <= 12}


def named_days(text: str, today: date | None) -> set[tuple[int, int]]:
    """day_months plus «сегодня», «завтра», «послезавтра» (бүгүн, эртең, бүрсүгүнү) counted from today."""
    out = day_months(text)
    if today is not None:
        for pattern, shift in _RELATIVE.items():
            if re.search(pattern, text, re.I):
                d = today + timedelta(days=shift)
                out.add((d.day, d.month))
    return out


def weekdays(text: str) -> set[int]:
    return {i for i, pattern in enumerate(_WEEKDAYS) if re.search(pattern, text, re.I)}


def sums(text: str) -> set[int]:
    return {int(re.sub(_GAP, "", x)) for x in _SUM.findall(text)} | {int(x) for x in _SUM_C.findall(text)}


def _keep(reply: str, wrong, done: str, claim=CLAIM) -> tuple[str, list[str]]:
    """(the reply without the claim sentences `wrong` rejects, the claim sentences kept). Removed in place: the other
    sentences, lines and line breaks stay as the model wrote them. When every claim went, `done` («Записала вас.»)
    takes the place of the first one removed."""
    claims: list[str] = []
    removed: list[tuple[int, int, int]] = []  # (line, start, end)
    lines = (reply or "").split("\n")
    for no, line in enumerate(lines):
        for a, b in _spans(line):
            sentence = line[a:b].strip()
            if claim.search(sentence):
                if wrong(sentence):
                    removed.append((no, a, b))
                else:
                    claims.append(sentence)
    first = removed[0] if removed and not claims else None
    out = []
    for no, line in enumerate(lines):
        cuts = [(a, b) for n, a, b in removed if n == no]
        if not cuts:
            out.append(line)
            continue
        text, pos = "", 0
        for a, b in cuts:
            text += line[pos:a] + (done + " " if first == (no, a, b) else "")
            pos = b
        text = re.sub(r"[ \t]{2,}", " ", text + line[pos:]).strip()
        if text:
            out.append(text)
    result = "\n".join(out).strip()
    return (result or done), claims


def _join(head: str, line: str) -> str:
    return f"{head.rstrip()}\n{line}" if line else head


def with_booking(reply: str, booking: Booking, kyrgyz: bool, today: date | None = None) -> str:
    when = fmt_slot_ky(booking.start) if kyrgyz else fmt_slot(booking.start)
    line = (BOOKED_KY if kyrgyz else BOOKED_RU).format(when=when, who=booking.staff_name)
    booked_time, booked_day, booked_weekday = f"{booking.start:%H:%M}", (booking.start.day, booking.start.month), booking.start.weekday()

    def wrong(sentence: str) -> bool:
        times, days, week = clock_times(sentence), named_days(sentence, today), weekdays(sentence)
        return bool(times and booked_time not in times) or bool(days and days != {booked_day}) \
            or bool(week and week != {booked_weekday})

    head, claims = _keep(reply, wrong, DONE_BOOKING_KY if kyrgyz else DONE_BOOKING_RU)
    exact = any(booked_time in clock_times(c) and booked_day in day_months(c) for c in claims)
    return _join(head, "" if exact else line)


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
    stems = {r.name.split()[0].lower()[:4]: r.quantity for r in facts.lines if r.name.split()}

    def wrong(sentence: str) -> bool:
        named = sums(sentence)
        total_word = bool(named and facts.total is not None and TOTAL_WORD.search(sentence) and facts.total not in named)
        return bool(named - facts.known) or total_word or _other_quantity(sentence, stems)

    head, _ = _keep(reply, wrong, DONE_ORDER_KY if kyrgyz else DONE_ORDER_RU,
                    re.compile(f"{CLAIM.pattern}|{TOTAL_WORD.pattern}", re.I))
    return _join(head, order_line(facts, kyrgyz))


def _other_quantity(sentence: str, stems: dict[str, int]) -> bool:
    """«3 плова» or «плов x3» for an order of 2 × Плов."""
    for n1, w1, w2, n2 in _QTY.findall(sentence):
        number, word = (n1, w1) if n1 else (n2, w2)
        qty = stems.get(word.lower()[:4])
        if qty is not None and int(number) != qty:
            return True
    return False


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
    head, _ = _keep(reply, lambda sentence: bool(day_months(sentence) - allowed), done)
    if head == done and fixed and not kyrgyz:
        return fixed  # nothing of the reply is left: the niche's own full confirmation, which already has the dates
    return _join(head, stay_line(stay, hall, with_guests, kyrgyz))


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]

