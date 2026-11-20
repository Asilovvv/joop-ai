"""Public menu / price list /m/<slug> with printable QR codes (one per table), managed in /panel/menu."""

from __future__ import annotations

import io
import re
from urllib.parse import quote

import segno
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response
from markupsafe import Markup
from sqlmodel import select

from .. import page_booking, samples
from ..db import new_session
from ..models import Business, Service
from ..niches import get_pack
from ..studio import clean_booking_url, phone_digits
from .app import _back, _business, _check_csrf, _flash, _render, templates

router = APIRouter()
MAX_TABLES = 60

TEXT = {
    "ru": {"order": "Заказать", "ask": "Задать вопрос", "book": "Записаться", "none": "Сейчас нет", "table": "Стол", "free": "бесплатно",
           "som": "сом", "other": "Другое", "hours": "Часы работы", "address": "Адрес", "phone": "Телефон",
           "masters": "Мастера", "nearest": "Ближайшее свободное время", "write": "Написать и записаться", "web": "Чат на сайте",
           "answers": "Отвечает ИИ-администратор — в любое время, записывает в свободное окно", "online": "Записаться онлайн"},
    "ky": {"order": "Буйрутма берүү", "ask": "Суроо берүү", "book": "Жазылуу", "none": "Азыр жок", "table": "Үстөл", "free": "акысыз",
           "som": "сом", "other": "Башкалар", "hours": "Иш убактысы", "address": "Дарек", "phone": "Телефон",
           "masters": "Усталар", "nearest": "Жакынкы бош убакыт", "write": "Жазып, жазылуу", "web": "Сайттагы чат",
           "answers": "ИИ-администратор жооп берет — каалаган убакта, бош убакытка жазат",
           "online": "Онлайн жазылуу"},  # проверить носителем
}


def menu_url(base: str, slug: str, table: int | None = None) -> str:
    return f"{base}/m/{slug}" + (f"?t={table}" if table else "")


def qr_svg(url: str, scale: int = 5, sized: bool = False) -> str:
    """SVG markup. Without `sized` it has only a viewBox, so CSS sets its size (panel, print sheet)."""
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True,
                                     title=url, svgclass="qr", lineclass=None, omitsize=not sized)
    return buf.getvalue().decode()


_NUMBER = r"\d(?:[\d\u00a0\u202f ]*\d)?(?:[.,]\d+)?"
PRICE_NUMBER = re.compile(rf"{_NUMBER}(?:\s*[–—-]\s*{_NUMBER})?")
# the business named a currency itself (a realty agency writes «120 000 $»): no «сом» on top of it
CURRENCY = re.compile(r"сом|kgs|\d\s*с\.|[$€₽₸£¥]|\b(?:usd|eur|rub|руб|тенге|тг|сум|у\.\s?е)\b", re.I)
# a number right before one of these is a quantity («1 кг — 450», «60 минут — 1 200»), not the price
UNIT = re.compile(r"\s*(?:кг|гр?|мл|л|шт|мм|см|м²|м2|м|мин|минут[аы]?|час(?:а|ов)?|ч|сут(?:ок|ки)?|дн(?:я|ей)?|день|"
                  r"ноч(?:ь|и|ей)|мес(?:яц(?:а|ев)?)?|чел(?:овек)?|порц(?:ия|ии|ий)?|занят(?:ие|ия|ий)|урок(?:а|ов)?|"
                  r"сеанс(?:а|ов)?|раз(?:а)?)\b", re.I)


def price_label(price: str, lang: str) -> str:
    """«сом» right after the price itself (a range counts as one), not after the unit: «3 500 сом за ночь»,
    «800 сом за 60 минут», «1 кг — 450 сом», «1 500–2 000 сом». A price in another currency, or with no price in it
    («по договорённости», «2 часа»), stays as written."""
    price = (price or "").strip()
    if not price:
        return ""
    if price == "0":
        return TEXT[lang]["free"]
    if CURRENCY.search(price):
        return price
    for m in PRICE_NUMBER.finditer(price):
        if not UNIT.match(price, m.end()):
            return f"{price[:m.end()]} {TEXT[lang]['som']}{price[m.end():]}"
    return price


def order_link(business: Business, lang: str, table: int | None, chat_url: str | None = None) -> tuple[str, str]:
    """(url, label) of the main button. WhatsApp links get a prefilled message with the table number.
    `chat_url`: None is the owner's saved link; "" asks what the button does with the field left empty."""
    phone = phone_digits(samples.customer_contact(business, "phone"))  # never the sign-up example's number
    own = business.menu_chat_url if chat_url is None else chat_url
    url = own or (f"https://wa.me/{phone}" if phone else "")
    if not url:
        return "", ""
    pack = get_pack(business.niche)
    label = TEXT[lang]["order"] if pack.has("order") else TEXT[lang]["book"] if pack.has("booking") else TEXT[lang]["ask"]
    if url.startswith("https://wa.me/") and table:
        url += ("&" if "?" in url else "?") + "text=" + quote(f"{TEXT[lang]['table']} {table}: ")
    return url, label


def main_button(business: Business, links: list[tuple[str, str]], lang: str, table: int | None,
                chat_url: str | None = None) -> tuple[str, str]:
    """The page's main button: the owner's link, else WhatsApp on the company phone; a booking niche without the
    owner's link, or a page with no phone, leads where the AI answers (`links`: channel_links)."""
    url, label = order_link(business, lang, table, chat_url)
    pack = get_pack(business.niche)
    own = business.menu_chat_url if chat_url is None else chat_url
    if links and (not url or (pack.has("booking") and not pack.has("order") and not own)):
        url = links[0][0]  # a booking niche: the button leads where the AI answers, not to the landline
        label = TEXT[lang]["book"] if pack.has("booking") else TEXT[lang]["ask"]
    return url, label


def empty_hint(business: Business, base: str) -> str:
    """For the panel: where the button leads when the owner leaves the link empty, as the public page decides."""
    url, _ = main_button(business, channel_links(business, base, "ru"), "ru", None, chat_url="")
    phone = samples.customer_contact(business, "phone")
    note = " (телефон в настройках — из примера, клиентам его не показываем)" if business.phone and not phone else ""
    if not url:
        where = "кнопки не будет: укажите телефон компании в настройках или включите ИИ"
    elif url.startswith(f"{base}/c/"):
        where = "кнопка ведёт в чат на сайте, где отвечает ИИ"
    elif url.startswith("https://t.me/"):
        where = "кнопка ведёт в вашего Telegram-бота, где отвечает ИИ"
    else:
        ai = business.bot_enabled and business.wa_phone_number_id and business.wa_access_token
        where = f"кнопка ведёт в WhatsApp на номер {phone}" + (", где отвечает ИИ" if ai else "")
    return f"Пусто — {where}{note}."


def channel_links(business: Business, base: str, lang: str) -> list[tuple[str, str]]:
    """Where a customer can write and the AI answers: the connected channels only, as the counter card does."""
    out: list[tuple[str, str]] = []
    if not business.bot_enabled:
        return out  # the AI is switched off: no «отвечает ИИ» promise
    phone = phone_digits(samples.customer_contact(business, "phone"))
    if business.wa_phone_number_id and business.wa_access_token and phone:
        out.append((f"https://wa.me/{phone}", "WhatsApp"))  # first: where most customers already write
    if business.telegram_bot_token and business.telegram_bot_username:
        out.append((f"https://t.me/{business.telegram_bot_username}", "Telegram"))
    out.append((f"{base}/c/{business.slug}", TEXT[lang]["web"]))
    return out


def book_url(base: str, business: Business, lang: str, slot_id: int = 0) -> str:
    """The booking page without a chat (joop/web/booking_page.py), optionally straight at one free time."""
    query = "&".join(x for x in (f"slot={slot_id}" if slot_id else "", "lang=ky" if lang == "ky" else "") if x)
    return f"{base}/m/{business.slug}/book" + (f"?{query}" if query else "")


def booking_extras(session, business: Business, base: str, lang: str) -> dict:
    """What a booking page adds to the price list: masters, the nearest free times, where to write. When customers
    may book on the page themselves (joop/page_booking.py), each nearest time leads to its booking form."""
    from ..models import Staff
    from ..slots import free_slots, lead_for
    from ..timeutil import fmt_slot, local_now, utcnow

    pack = get_pack(business.niche)
    if not pack.has("booking"):
        return {"masters": [], "nearest": [], "links": channel_links(business, base, lang), "page_booking": False}
    example = samples.hidden_from_customers(session, business, "web").staff  # sign-up example people are nobody
    masters = [m for m in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)  # noqa: E712
                                       .order_by(Staff.name)).all() if m.id not in example]
    now_local = local_now(business.timezone).replace(tzinfo=None)
    if not page_booking.unavailable(session, business, utcnow()):
        times = page_booking.one_per_time(page_booking.free_times(session, business, now_local))[:3]
        return {"masters": masters, "links": channel_links(business, base, lang), "page_booking": True,
                "nearest": [(fmt_slot(slot.start), book_url(base, business, lang, slot.id)) for slot, _ in times]}
    seen: dict = {}
    for slot, staff in free_slots(session, business.id, now_local, days=7, limit=60, exclude_staff=example,
                                  lead_minutes=lead_for(business)):
        seen.setdefault(slot.start, staff.name)
        if len(seen) == 3:
            break
    return {"masters": masters, "nearest": [(fmt_slot(at), "") for at in sorted(seen)],
            "links": channel_links(business, base, lang), "page_booking": False}


def _groups(items: list[Service], lang: str) -> list[tuple[str, list[Service]]]:
    groups: dict[str, list[Service]] = {}
    for s in items:
        groups.setdefault(s.category.strip() or "", []).append(s)
    named = [(k, v) for k, v in groups.items() if k]
    return named + ([(TEXT[lang]["other"] if named else "", groups[""])] if "" in groups else [])


# --- public page -------------------------------------------------------------------------------


def _enabled_business(s, slug: str) -> Business:
    b = s.exec(select(Business).where(Business.slug == slug)).first()
    if b is None or not b.menu_enabled:
        raise HTTPException(status_code=404)
    return b


@router.get("/m/{slug}")
def public_menu(request: Request, slug: str, t: int = 0, lang: str = "ru"):
    lang = lang if lang in TEXT else "ru"
    table = t if 0 < t <= MAX_TABLES else None
    with new_session() as s:
        b = _enabled_business(s, slug)
        example = samples.hidden_from_customers(s, b, "web").services  # the sign-up example's prices are not real
        items = [i for i in s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort, Service.id)).all()
                 if i.id not in example]
        from .app import _base_url

        extras = booking_extras(s, b, _base_url(request), lang)
    url, label = main_button(b, extras["links"], lang, table)
    if extras["page_booking"]:  # the owner turned on booking without a chat: the main button books
        url, label = book_url(_base_url(request), b, lang), TEXT[lang]["online"]
    pack = get_pack(b.niche)
    return templates.TemplateResponse(request, "menu_public.html", {
        "request": request, "b": b, "groups": _groups(list(items), lang), "lang": lang, "tx": TEXT[lang], "table": table,
        "order_url": url, "order_label": label, "price": price_label, "title": get_pack(b.niche).catalog_label,
        "has_ky": any(i.name_ky for i in items), "booking": get_pack(b.niche).has("booking"),
        "resources": pack.resource_label if lang == "ru" else TEXT[lang]["masters"], **extras,
        # the sign-up example's address and phone are fictional: not shown to customers (joop/samples.py)
        "address": samples.customer_contact(b, "address"), "phone": samples.customer_contact(b, "phone"),
        "hours": samples.customer_hours(b),
    })


@router.get("/m/{slug}/qr.svg")
def menu_qr(request: Request, slug: str, t: int = 0):
    from .app import _base_url

    with new_session() as s:
        b = _enabled_business(s, slug)
    table = t if 0 < t <= MAX_TABLES else None
    return Response(qr_svg(menu_url(_base_url(request), b.slug, table), scale=10, sized=True), media_type="image/svg+xml",
                    headers={"Content-Disposition": f'inline; filename="menu-{b.slug}{"-" + str(table) if table else ""}.svg"'})


# --- panel -------------------------------------------------------------------------------------


@router.get("/panel/menu")
def menu_page(request: Request):
    from .app import _base_url

    from ..timeutil import local_now, utcnow

    with new_session() as s:
        b = _business(s, request)
        count = len(s.exec(select(Service.id).where(Service.business_id == b.id)).all())
        left = samples.left(s, b)
        page_why = page_booking.unavailable(s, b, utcnow())
        page_times = len(page_booking.free_times(s, b, local_now(b.timezone).replace(tzinfo=None))) \
            if get_pack(b.niche).has("booking") else 0
    url = menu_url(_base_url(request), b.slug)
    return _render(request, "menu.html", "menu", b, url=url, qr=Markup(qr_svg(url)), count=count,
                   example_items=len(left.services), example_people=len(left.staff), empty_hint=empty_hint(b, _base_url(request)),
                   page_why=page_why, page_times=page_times, book_link=book_url(_base_url(request), b, "ru"))


@router.post("/panel/menu")
def menu_save(request: Request, enabled: str = Form(""), chat_url: str = Form(""), self_booking: str = Form(""),
              csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        b.menu_enabled = bool(enabled)
        if get_pack(b.niche).has("booking"):
            b.page_booking = bool(self_booking)  # customers book a free time on the page themselves (joop/page_booking.py)
        clean = clean_booking_url(chat_url)
        if chat_url.strip() and not clean:
            _flash(request, "Ссылка для заказа должна вести в t.me, wa.me или Instagram — она не сохранена.", "error")
        b.menu_chat_url = clean
        s.add(b)
        s.commit()
    _flash(request, "Сохранено." + (" Страница открыта по ссылке и QR-коду." if enabled else " Страница выключена."))
    return _back("/panel/menu")


@router.get("/panel/menu/print")
def menu_print(request: Request, tables: int = 0):
    from .app import _base_url

    tables = max(0, min(tables, MAX_TABLES))
    base = _base_url(request)
    with new_session() as s:
        b = _business(s, request)
    if not b.menu_enabled:
        _flash(request, "Сначала включите онлайн-страницу.", "error")
        return _back("/panel/menu")
    cards = [(None, Markup(qr_svg(menu_url(base, b.slug))))]
    cards += [(n, Markup(qr_svg(menu_url(base, b.slug, n)))) for n in range(1, tables + 1)]
    return templates.TemplateResponse(request, "menu_print.html", {
        "request": request, "b": b, "cards": cards, "title": get_pack(b.niche).catalog_label,
    })
