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

from .. import samples
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
           "answers": "Отвечает ИИ-администратор — в любое время, записывает в свободное окно"},
    "ky": {"order": "Буйрутма берүү", "ask": "Суроо берүү", "book": "Жазылуу", "none": "Азыр жок", "table": "Үстөл", "free": "акысыз",
           "som": "сом", "other": "Башкалар", "hours": "Иш убактысы", "address": "Дарек", "phone": "Телефон",
           "masters": "Усталар", "nearest": "Жакынкы бош убакыт", "write": "Жазып, жазылуу", "web": "Сайттагы чат",
           "answers": "ИИ-администратор жооп берет — каалаган убакта, бош убакытка жазат"},  # проверить носителем
}


def menu_url(base: str, slug: str, table: int | None = None) -> str:
    return f"{base}/m/{slug}" + (f"?t={table}" if table else "")


def qr_svg(url: str, scale: int = 5, sized: bool = False) -> str:
    """SVG markup. Without `sized` it has only a viewBox, so CSS sets its size (panel, print sheet)."""
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True,
                                     title=url, svgclass="qr", lineclass=None, omitsize=not sized)
    return buf.getvalue().decode()


def price_label(price: str, lang: str) -> str:
    price = (price or "").strip()
    if not price:
        return ""
    if price == "0":
        return TEXT[lang]["free"]
    if re.search(r"\d", price) and "сом" not in price.lower():
        return f"{price} {TEXT[lang]['som']}"
    return price


def order_link(business: Business, lang: str, table: int | None) -> tuple[str, str]:
    """(url, label) of the main button. WhatsApp links get a prefilled message with the table number."""
    url = business.menu_chat_url or (f"https://wa.me/{phone_digits(business.phone)}" if phone_digits(business.phone) else "")
    if not url:
        return "", ""
    pack = get_pack(business.niche)
    label = TEXT[lang]["order"] if pack.has("order") else TEXT[lang]["book"] if pack.has("booking") else TEXT[lang]["ask"]
    if url.startswith("https://wa.me/") and table:
        url += ("&" if "?" in url else "?") + "text=" + quote(f"{TEXT[lang]['table']} {table}: ")
    return url, label


def channel_links(business: Business, base: str, lang: str) -> list[tuple[str, str]]:
    """Where a customer can write and the AI answers: the connected channels only, as the counter card does."""
    out: list[tuple[str, str]] = []
    if not business.bot_enabled:
        return out  # the AI is switched off: no «отвечает ИИ» promise
    if business.wa_phone_number_id and business.wa_access_token and phone_digits(business.phone):
        out.append((f"https://wa.me/{phone_digits(business.phone)}", "WhatsApp"))  # first: where most customers already write
    if business.telegram_bot_token and business.telegram_bot_username:
        out.append((f"https://t.me/{business.telegram_bot_username}", "Telegram"))
    out.append((f"{base}/c/{business.slug}", TEXT[lang]["web"]))
    return out


def booking_extras(session, business: Business, base: str, lang: str) -> dict:
    """What a booking page adds to the price list: masters, the nearest free times, where to write."""
    from ..models import Staff
    from ..slots import free_slots, lead_for
    from ..timeutil import fmt_slot, local_now

    pack = get_pack(business.niche)
    if not pack.has("booking"):
        return {"masters": [], "nearest": [], "links": channel_links(business, base, lang)}
    example = samples.hidden_from_customers(session, business, "web").staff  # sign-up example people are nobody
    masters = [m for m in session.exec(select(Staff).where(Staff.business_id == business.id, Staff.active == True)  # noqa: E712
                                       .order_by(Staff.name)).all() if m.id not in example]
    seen: dict = {}
    for slot, staff in free_slots(session, business.id, local_now(business.timezone), days=7, limit=60, exclude_staff=example,
                                  lead_minutes=lead_for(business)):
        seen.setdefault(slot.start, staff.name)
        if len(seen) == 3:
            break
    return {"masters": masters, "nearest": [fmt_slot(at) for at in sorted(seen)], "links": channel_links(business, base, lang)}


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
    url, label = order_link(b, lang, table)
    pack = get_pack(b.niche)
    if extras["links"] and (not url or (pack.has("booking") and not pack.has("order") and not b.menu_chat_url)):
        url = extras["links"][0][0]  # a booking niche: the button leads where the AI answers, not to the landline
        label = TEXT[lang]["book"] if pack.has("booking") else TEXT[lang]["ask"]
    return templates.TemplateResponse(request, "menu_public.html", {
        "request": request, "b": b, "groups": _groups(list(items), lang), "lang": lang, "tx": TEXT[lang], "table": table,
        "order_url": url, "order_label": label, "price": price_label, "title": get_pack(b.niche).catalog_label,
        "has_ky": any(i.name_ky for i in items), "booking": get_pack(b.niche).has("booking"),
        "resources": pack.resource_label if lang == "ru" else TEXT[lang]["masters"], **extras,
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

    with new_session() as s:
        b = _business(s, request)
        count = len(s.exec(select(Service.id).where(Service.business_id == b.id)).all())
        left = samples.left(s, b)
    url = menu_url(_base_url(request), b.slug)
    return _render(request, "menu.html", "menu", b, url=url, qr=Markup(qr_svg(url)), count=count,
                   example_items=len(left.services), example_people=len(left.staff))


@router.post("/panel/menu")
def menu_save(request: Request, enabled: str = Form(""), chat_url: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        b.menu_enabled = bool(enabled)
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
