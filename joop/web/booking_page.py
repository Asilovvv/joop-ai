"""Booking by link without a chat, the customer's side: /m/<slug>/book (rules and limits: joop/page_booking.py).

Three steps on plain links and one form, no script: pick a person (or «Любой») and a day, then a time; give a name
and a phone; see the booking with a calendar file. Times are re-checked on every step: a time someone else took in
the meantime sends the customer back to the list with a line saying so.
"""

from __future__ import annotations

import time as time_module
from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlmodel import select

from .. import page_booking as pb, samples
from ..api import book
from ..confirm import WEEKDAYS_KY
from ..db import new_session
from ..dispatch import notify_admins
from ..models import Business, Service, Slot, Staff
from ..niches import get_pack
from ..phone import display_phone, normalize_phone
from ..timeutil import WEEKDAYS_FULL, WEEKDAYS_SHORT, local_now, utcnow
from .app import _rt, _settings, client_ip, templates
from .menu import _enabled_business, book_url, channel_links, people_title, price_label

router = APIRouter()
_by_address: dict[str, tuple[str, int]] = {}  # "<business id>|<address>" -> (day, page bookings); reset with the process

WEEKDAYS_KY_FULL = ("дүйшөмбү", "шейшемби", "шаршемби", "бейшемби", "жума", "ишемби", "жекшемби")  # проверить носителем
TEXT = {
    "ru": {"title": "Запись онлайн", "any": "Любой", "day": "День", "time": "Время", "back": "← Другое время",
           "none": "Свободного времени на ближайшие две недели нет. Напишите или позвоните нам — подберём время.",
           "name": "Ваше имя", "phone": "Телефон", "service": "Услуга", "service_none": "Не выбрана — уточним на месте",
           "party": "Гостей", "submit": "Записаться", "privacy": "Политика конфиденциальности",
           "consent": "Нажимая «Записаться», вы соглашаетесь на обработку имени и телефона для записи.",
           "staff": "Вы вошли в панель этой компании: запись будет настоящей и займёт время. Если это проверка — отмените её "
                    "в «Записях».",
           "done": "Вы записаны", "wait": "Ждём вас:", "at": "в", "remind": "Напомнить в Telegram",
           "remind_hint": "Напомним накануне — подтвердите запись одним словом «да».",
           "reminded": "Напоминание придёт в Telegram накануне.", "calendar": "Добавить в календарь",
           "change": "Если планы изменятся — напишите или позвоните нам:", "again": "Записаться ещё",
           "cancelled": "Эта запись отменена. Выберите другое время или свяжитесь с нами.", "call": "Позвонить",
           "menu": "Цены и контакты",
           "errors": {
               "taken": "Это время только что заняли — выберите другое.",
               "stale": "Страница устарела — выберите время ещё раз.",
               "contact": "Укажите имя и номер телефона, например 0555 123 456.",
               "party": "За этим столом меньше мест — выберите другой стол или время.",
               "phone": f"На этот номер уже есть {pb.PER_PHONE_AHEAD} записи вперёд. Чтобы записаться ещё, напишите или "
                        "позвоните нам.",
               "busy": "Онлайн-запись на сегодня закрыта — позвоните или напишите нам.",
               "address": "С этого адреса сегодня уже много записей — позвоните или напишите нам.",
               "again": "Не получилось записать — проверьте данные и нажмите «Записаться» ещё раз.",
           }},
    # проверить носителем: every Kyrgyz line below
    "ky": {"title": "Онлайн жазылуу", "any": "Каалаган", "day": "Күн", "time": "Убакыт", "back": "← Башка убакыт",
           "none": "Жакынкы эки жумада бош убакыт жок. Бизге жазыңыз же чалыңыз — убакыт табабыз.",
           "name": "Атыңыз", "phone": "Телефон", "service": "Кызмат", "service_none": "Тандалган жок — жеринде тактайбыз",
           "party": "Коноктор", "submit": "Жазылуу", "privacy": "Купуялык саясаты",
           "consent": "«Жазылуу» баскычын басып, жазылуу үчүн атыңыз жана телефонуңуз иштетилишине макул болосуз.",
           "staff": "Сиз бул компаниянын панелине кирдиңиз: жазылуу чыныгы болот жана убакытты ээлейт. Текшерүү болсо — "
                    "«Жазылуулар» бөлүмүндө жокко чыгарыңыз.",
           "done": "Сиз жазылдыңыз", "wait": "Сизди күтөбүз:", "at": "саат", "remind": "Telegram аркылуу эскертүү",
           "remind_hint": "Бир күн мурун эскертебиз — жазылууну «ооба» деп ырастаңыз.",
           "reminded": "Эскертүү бир күн мурун Telegram'га келет.", "calendar": "Календарга кошуу",
           "change": "Пландар өзгөрсө — бизге жазыңыз же чалыңыз:", "again": "Дагы жазылуу",
           "cancelled": "Бул жазылуу жокко чыгарылды. Башка убакыт тандаңыз же биз менен байланышыңыз.", "call": "Чалуу",
           "menu": "Баалар жана байланыш",
           "errors": {
               "taken": "Бул убакытты азыр эле ээлеп коюшту — башкасын тандаңыз.",
               "stale": "Барак эскирип калды — убакытты кайра тандаңыз.",
               "contact": "Атыңызды жана телефон номериңизди жазыңыз, мисалы 0555 123 456.",
               "party": "Бул үстөлдө орун азыраак — башка үстөл же убакыт тандаңыз.",
               "phone": f"Бул номерге алдыда {pb.PER_PHONE_AHEAD} жазылуу бар. Дагы жазылуу үчүн бизге жазыңыз же чалыңыз.",
               "busy": "Бүгүн онлайн жазылуу жабык — бизге чалыңыз же жазыңыз.",
               "address": "Бул даректен бүгүн жазылуулар көп — бизге чалыңыз же жазыңыз.",
               "again": "Жазуу мүмкүн болгон жок — маалыматты текшерип, «Жазылуу» баскычын кайра басыңыз.",
           }},
}


def _now() -> float:
    """Wall-clock seconds for the form's age (tests move it)."""
    return time_module.time()


def _lang(lang: str) -> str:
    return lang if lang in TEXT else "ru"


def _day_label(day: date, lang: str) -> str:
    return f"{(WEEKDAYS_KY if lang == 'ky' else WEEKDAYS_SHORT)[day.weekday()]} {day:%d.%m}"


def _date_long(at: datetime, lang: str) -> str:
    return f"{(WEEKDAYS_KY_FULL if lang == 'ky' else WEEKDAYS_FULL)[at.weekday()]}, {at:%d.%m.%Y}"


def _who(member: Staff) -> str:
    return member.name + (f", {member.role}" if member.role else "")


def _switch(request: Request, lang: str) -> str:
    """The same step in the other language; after a refused form, the list (its time may be gone by then)."""
    params = {k: v for k, v in request.query_params.items() if k not in ("lang", "why")} if request.method == "GET" else {}
    if lang == "ky":
        params["lang"] = "ky"
    return request.url.path + (f"?{urlencode(params)}" if params else "")


def _staff_view(request: Request, b: Business) -> bool:
    """A browser logged in to this business's panel. Read only: a visitor never gets a cookie."""
    return request.scope.get("session", {}).get("bid") == b.id


def _page(request: Request, b: Business, lang: str, step: str, status: int = 200, **context) -> Response:
    from .app import _base_url

    pack = get_pack(b.niche)
    base = _base_url(request)
    return templates.TemplateResponse(request, "book_public.html", {
        "request": request, "b": b, "lang": lang, "tx": TEXT[lang], "step": step, "resources": people_title(pack, lang),
        "menu_url": f"/m/{b.slug}" + ("?lang=ky" if lang == "ky" else ""), "book_url": book_url("", b, lang),
        "staff_view": _staff_view(request, b),
        "phone": samples.customer_contact(b, "phone"), "address": samples.customer_contact(b, "address"),
        "links": channel_links(b, base, lang), "switch_ru": _switch(request, "ru"), "switch_ky": _switch(request, "ky"),
        **context,
    }, status_code=status)


def _pick(request: Request, b: Business, lang: str, rows: list[tuple[Slot, Staff]], day: str, staff: int,
          error: str = "", status: int = 200) -> Response:
    masters = sorted({m.id: m for _, m in rows}.values(), key=lambda m: (m.name, m.id))
    member = next((m for m in masters if m.id == staff), None)
    shown = [r for r in rows if r[1].id == member.id] if member else pb.one_per_time(rows)
    days = pb.by_day(shown)
    try:
        chosen = date.fromisoformat(day) if day else None
    except ValueError:
        chosen = None
    if chosen not in days:
        chosen = min(days) if days else None
    keep = "&".join(x for x in (f"staff={member.id}" if member else "", "lang=ky" if lang == "ky" else "") if x)
    return _page(request, b, lang, "pick", status, error=TEXT[lang]["errors"].get(error, ""),
                 masters=masters if len(masters) > 1 else [], member=member, keep=keep,
                 days=[(d, _day_label(d, lang)) for d in sorted(days)], chosen=chosen,
                 times=[(slot.id, f"{slot.start:%H:%M}") for slot, _ in days.get(chosen, [])])


def _form(request: Request, s, b: Business, lang: str, slot: Slot, member: Staff, error: str = "", status: int = 200,
          values: dict | None = None) -> Response:
    hidden = samples.hidden_from_customers(s, b, "web").services  # the sign-up example's prices are not real
    services = [x for x in s.exec(select(Service).where(Service.business_id == b.id, Service.available == True)  # noqa: E712
                                  .order_by(Service.sort, Service.id)).all() if x.id not in hidden]
    token = pb.form_token(_settings(request).session_secret, b.id, slot.id, int(_now()))
    return _page(request, b, lang, "form", status, error=TEXT[lang]["errors"].get(error, ""), slot=slot, who=_who(member),
                 when=f"{_date_long(slot.start, lang)} · {slot.start:%H:%M}", services=services, price=price_label,
                 party_max=pb.party_limit(slot, member), token=token, values=values or {})


@router.get("/m/{slug}/book")
def book_page(request: Request, slug: str, day: str = "", staff: int = 0, slot: int = 0, lang: str = "ru", why: str = ""):
    lang = _lang(lang)
    with new_session() as s:
        b = _enabled_business(s, slug)
        if pb.unavailable(s, b, utcnow()):
            return RedirectResponse(f"/m/{b.slug}" + ("?lang=ky" if lang == "ky" else ""), status_code=303)
        rows = pb.free_times(s, b, local_now(b.timezone).replace(tzinfo=None))
        if slot:
            chosen = next(((sl, m) for sl, m in rows if sl.id == slot), None)
            if chosen:
                return _form(request, s, b, lang, *chosen)
            why = "taken"  # gone since the list was shown
        return _pick(request, b, lang, rows, day, staff, why)


@router.post("/m/{slug}/book")
def book_submit(request: Request, background: BackgroundTasks, slug: str, slot: int = Form(0), name: str = Form(""),
                phone: str = Form(""), service: int = Form(0), party: int = Form(1), t: str = Form(""),
                hp_note: str = Form(""), lang: str = Form("ru")):
    lang = _lang(lang)
    values = {"name": name[:60], "phone": phone[:30], "service": service, "party": party}
    with new_session() as s:
        b = _enabled_business(s, slug)
        to_list = f"/m/{b.slug}/book?why=%s" + ("&lang=ky" if lang == "ky" else "")
        now_utc = utcnow()
        if pb.unavailable(s, b, now_utc):
            return RedirectResponse(f"/m/{b.slug}", status_code=303)
        now_local = local_now(b.timezone).replace(tzinfo=None)
        chosen = next(((sl, m) for sl, m in pb.free_times(s, b, now_local) if sl.id == slot), None)
        if chosen is None:
            return RedirectResponse(to_list % "taken", status_code=303)
        the_slot, member = chosen
        age = pb.form_age(_settings(request).session_secret, b.id, the_slot.id, t, _now())
        if age is not None and age > pb.MAX_FILL:
            return RedirectResponse(to_list % "stale", status_code=303)
        if hp_note.strip() or age is None or age < pb.MIN_FILL:  # a script: the hidden field, a forged or instant form
            return _form(request, s, b, lang, the_slot, member, "again", 400, values)
        staff = _staff_view(request, b)  # a receptionist booking callers all day from one office address
        key, today = f"{b.id}|{client_ip(request)}", now_local.date().isoformat()
        day_seen, used = _by_address.get(key, (today, 0))
        used = used if day_seen == today else 0
        if used >= pb.PER_ADDRESS_DAY and not staff:
            return _form(request, s, b, lang, the_slot, member, "address", 429, values)
        clean_name, clean_phone = " ".join(name.split())[:60], normalize_phone(phone)
        if not clean_name or not clean_phone:
            return _form(request, s, b, lang, the_slot, member, "contact", 422, values)
        refused = pb.refused(s, b, clean_phone, now_local, now_utc)
        if refused:
            return _form(request, s, b, lang, the_slot, member, refused, 429, values)
        if not 1 <= party <= pb.party_limit(the_slot, member):
            return _form(request, s, b, lang, the_slot, member, "party", 422, values)
        hidden = samples.hidden_from_customers(s, b, "web").services
        picked = s.get(Service, service) if service > 0 else None  # never free text: staff read it in their alerts
        service_name = picked.name if picked and picked.business_id == b.id and picked.available and picked.id not in hidden else ""
        done = book(s, b, {"slot_id": the_slot.id, "name": clean_name, "phone": clean_phone, "service": service_name,
                           "party_size": party}, now_local, now_utc, source=pb.SOURCE)
        if done.booking is None:
            if done.reason in ("contact", "party"):
                return _form(request, s, b, lang, the_slot, member, done.reason, 422, values)
            return RedirectResponse(to_list % "taken", status_code=303)
        if staff:  # staff booking a caller, or the owner trying the page: real, as the page says,
            done.booking.by_staff = True  # only not a customer who found the page by themselves
            s.add(done.booking)
        s.commit()
        s.refresh(done.booking)
        if not staff:
            _by_address[key] = (today, used + 1)
        background.add_task(notify_admins, _rt(request), b, [pb.staff_note(done.booking)])
        done_url = f"/m/{b.slug}/book/{pb.done_token(_settings(request).session_secret, done.booking)}"
    return RedirectResponse(done_url + ("?lang=ky" if lang == "ky" else ""), status_code=303)


def _booked(request: Request, s, slug: str, token: str):
    b = _enabled_business(s, slug)
    booking = pb.booking_for(s, b, _settings(request).session_secret, token)
    if booking is None:
        raise HTTPException(status_code=404)
    return b, booking


@router.get("/m/{slug}/book/{token}")
def booked_page(request: Request, slug: str, token: str, lang: str = "ru"):
    lang = _lang(lang)
    with new_session() as s:
        b, x = _booked(request, s, slug, token)
        return _page(request, b, lang, "done", booking=x, when=f"{_date_long(x.start, lang)}, {TEXT[lang]['at']} {x.start:%H:%M}",
                     ics_url=f"/m/{b.slug}/book/{token}/booking.ics", cancelled=x.status != "booked",
                     phone_link=display_phone(samples.customer_contact(b, "phone")),
                     remind_url="" if x.chat_id else pb.remind_link(b, x, local_now(b.timezone).replace(tzinfo=None), lang), reminded=x.channel == "telegram")


@router.get("/m/{slug}/book/{token}/booking.ics")
def booked_calendar(request: Request, slug: str, token: str):
    with new_session() as s:
        b, x = _booked(request, s, slug, token)
        if x.status != "booked":
            raise HTTPException(status_code=404)
        slot = s.get(Slot, x.slot_id) if x.slot_id else None
        body = pb.ics(b, x, slot.duration_min if slot else 60, samples.customer_contact(b, "address"),
                      samples.customer_contact(b, "phone"), utcnow())
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="booking.ics"', "Cache-Control": "no-store"})


def reset_limits() -> None:
    """For tests."""
    _by_address.clear()
