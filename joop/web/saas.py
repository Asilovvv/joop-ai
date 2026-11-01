"""Self-serve SaaS: sign-up, launch checklist, test chat, billing, and the founder console.

Business side:  /signup -> /panel/setup (checklist) -> /panel/try (chat with the AI) -> /panel/billing
Founder side:   /owner (all businesses, money, actions) and /owner/prospects (sales pipeline with AI drafts)
"""

from __future__ import annotations

import csv
import hmac
import io
import logging
import re
import secrets
import time
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func
from sqlmodel import Session, select

from .. import billing, partners
from ..agent.engine import handle_incoming
from ..channels.base import IncomingMessage
from ..db import new_session
from ..models import (
    Booking, Business, Conversation, Lead, Message, Order, Partner, PartnerPayout, Payment, Prospect, Service, Subscription,
)
from ..niches import all_packs, get_pack
from ..presets import SlugTaken, create_business
from ..pricing import empty_usage
from ..timeutil import utcnow
from .app import _back, _base_url, _business, _check_csrf, _csrf, _flash, _render, _rt, _settings, templates

log = logging.getLogger(__name__)
router = APIRouter()

TRY_CHAT_ID = "panel-test"
TRY_DAILY_LIMIT = 60  # test-chat messages per business per day: open sign-up must not burn the AI budget
PROSPECT_STATUSES = {
    "new": "Новый",
    "contacted": "Написали",
    "replied": "Ответил",
    "demo": "Демо",
    "trial": "Пробный",
    "paid": "Платит",
    "lost": "Отказ",
}

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "ң": "ng", "о": "o", "ө": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ү": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})


def slugify(name: str) -> str:
    """Latin login from a business name: "Ак-Тиш Дент" -> "ak-tish-dent"."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().translate(_TRANSLIT)).strip("-")
    return (s[:30].strip("-") or "biz")


def unique_slug(session: Session, name: str) -> str:
    base = slugify(name)
    if base.startswith("site-demo"):
        base = "c-" + base  # reserved for the live demo on the site (joop/web/demo.py)
    slug, n = base, 2
    while session.exec(select(Business.id).where(Business.slug == slug)).first() is not None:
        slug, n = f"{base}-{n}", n + 1
    return slug


# --- sign-up --------------------------------------------------------------------------------------


@router.get("/signup")
def signup_form(request: Request):
    if not _settings(request).signup_enabled:
        raise HTTPException(status_code=404)
    ref = request.query_params.get("ref", "")
    if ref:
        with new_session() as s:
            if partners.find_active(s, ref):
                request.session["ref"] = ref.strip().lower()
    packs = {k: p for k, p in all_packs().items()}
    chosen = request.query_params.get("niche", "")
    return _render(request, "signup.html", "signup", None, packs=packs, trial_days=_settings(request).trial_days,
                   chosen=chosen if chosen in packs else "dental")


@router.post("/signup")
def signup(
    request: Request,
    name: str = Form(""),
    niche: str = Form("other"),
    contact_name: str = Form(""),
    phone: str = Form(""),
    password: str = Form(""),
    website: str = Form(""),  # honeypot: people do not see it, bots fill it
    csrf: str = Form(""),
):
    settings = _settings(request)
    if not settings.signup_enabled:
        raise HTTPException(status_code=404)
    _check_csrf(request, csrf)
    if website:
        return _back("/signup")
    last = request.session.get("signup_at", 0)
    if time.time() - float(last or 0) < 30:
        _flash(request, "Подождите полминуты перед повторной регистрацией.", "error")
        return _back("/signup")
    name, phone = name.strip()[:120], phone.strip()[:40]
    if len(name) < 2 or len(password) < 8 or len(re.sub(r"\D", "", phone)) < 9:
        _flash(request, "Укажите название, телефон и пароль не короче 8 символов.", "error")
        return _back("/signup")
    if niche not in all_packs():
        niche = "other"
    now = utcnow()
    with new_session() as s:
        slug = unique_slug(s, name)
        try:
            business = create_business(s, slug=slug, name=name, password=password, niche=niche, demo=True, now_utc=now)
        except SlugTaken:
            _flash(request, "Не получилось создать компанию, попробуйте ещё раз.", "error")
            return _back("/signup")
        # The demo profile brings a sample price list and hours; its address and phone are fake.
        business.address = ""
        business.phone = phone
        source = "signup-demo" if request.session.get("demo_tried") else "signup"  # wrote to the live demo first
        billing.start_trial(s, business, settings.trial_days, now, source, contact_name, phone)
        partner = partners.find_active(s, request.session.get("ref", ""))
        if partner is not None:
            partners.attach(s, business.id, partner)
        s.add(business)
        s.commit()
        bid = business.id
    log.info("New sign-up: %s (%s)", slug, niche)
    request.session.clear()
    request.session["bid"] = bid
    request.session["signup_at"] = time.time()
    _flash(request, f"Готово! Ваш логин: {slug}. Мы заполнили пример прайса — замените его своими данными.")
    return _back("/panel/setup")


# --- launch checklist -------------------------------------------------------------------------------


def checklist(s: Session, b: Business, now) -> list[dict[str, Any]]:
    services = s.exec(select(func.count()).select_from(Service).where(Service.business_id == b.id)).one()
    tested = s.exec(
        select(func.count()).select_from(Conversation).where(Conversation.business_id == b.id, Conversation.channel == "console")
    ).one()
    real = s.exec(
        select(func.count()).select_from(Conversation).where(Conversation.business_id == b.id, Conversation.channel != "console")
    ).one()
    channel = bool(b.telegram_bot_token or (b.wa_phone_number_id and b.wa_access_token) or (b.ig_account_id and b.ig_access_token))
    sub = billing.get_subscription(s, b.id)
    paid = bool(sub and billing.state(sub, now).code == "active")
    return [
        {"done": bool(b.address and b.phone and b.hours_text), "title": "Контакты и часы работы", "href": "/panel/settings",
         "hint": "Адрес, телефон и часы — ИИ отвечает только тем, что здесь написано."},
        {"done": services > 0, "title": f"{get_pack(b.niche).catalog_label}: {services}", "href": "/panel/services",
         "hint": "Мы добавили пример. Замените цены и названия на свои; кыргызские названия — по желанию."},
        {"done": tested > 0, "title": "Проверьте ИИ в тестовом чате", "href": "/panel/try",
         "hint": "Напишите как клиент: по-русски и по-кыргызски, спросите цену, запишитесь."},
        {"done": channel, "title": "Подключите Telegram-бота", "href": "#telegram",
         "hint": "Одно действие: вставьте токен от @BotFather ниже. WhatsApp и Instagram — в разделе «Каналы»."},
        {"done": bool(b.admin_chat_ids), "title": "Получайте заявки в Telegram", "href": "/panel/settings",
         "hint": "Отправьте боту код из «Настроек», и новые записи будут приходить вам."},
        {"done": real > 0, "title": "Первый настоящий клиент", "href": "/panel/conversations",
         "hint": "Поставьте ссылку на бота в Instagram и 2ГИС."},
        {"done": paid, "title": "Оплата", "href": "/panel/billing", "hint": "После пробного периода ИИ работает по подписке."},
    ]


@router.get("/panel/setup")
def setup_page(request: Request):
    now = utcnow()
    with new_session() as s:
        b = _business(s, request)
        items = checklist(s, b, now)
        sub = billing.get_subscription(s, b.id)
        st = billing.state(sub, now) if sub else None
    done = sum(1 for i in items if i["done"])
    return _render(request, "setup.html", "setup", b, items=items, done=done, total=len(items), sub_state=st)


@router.post("/panel/setup/telegram")
def setup_telegram(request: Request, token: str = Form(""), csrf: str = Form("")):
    """One step: paste the BotFather token -> token checked, saved, webhook set."""
    _check_csrf(request, csrf)
    token = token.strip()
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", token):
        _flash(request, "Это не похоже на токен бота. Скопируйте его целиком из сообщения @BotFather.", "error")
        return _back("/panel/setup#telegram")
    settings = _settings(request)
    with new_session() as s:
        b = _business(s, request)
        others = s.exec(select(Business).where(Business.id != b.id, Business.telegram_bot_token != "")).all()
        if any(o.telegram_bot_token == token for o in others):  # tokens are encrypted: compare after decryption
            _flash(request, "Этот бот уже подключён к другой компании.", "error")
            return _back("/panel/setup#telegram")
        b.telegram_bot_token = token
        s.add(b)
        s.commit()
    client = _rt(request).telegram(b)
    me = client.get_me() if client else None
    if not me:
        _flash(request, "Telegram не принял токен. Проверьте его у @BotFather.", "error")
        return _back("/panel/setup#telegram")
    if not settings.public_base_url.startswith("https://"):
        _flash(request, f"Токен бота @{me.get('username', '')} сохранён. Чтобы бот отвечал, серверу нужен адрес https (PUBLIC_BASE_URL).", "error")
        return _back("/panel/setup")
    if client.set_webhook(f"{settings.public_base_url}/webhooks/telegram/{b.slug}", b.telegram_secret):
        _flash(request, f"Бот @{me.get('username', '')} подключён. Напишите ему — ИИ ответит.")
    else:
        _flash(request, "Не удалось подключить бота. Попробуйте ещё раз через минуту.", "error")
    return _back("/panel/setup")


# --- test chat in the panel ------------------------------------------------------------------------------


@router.get("/panel/try")
def try_page(request: Request):
    with new_session() as s:
        b = _business(s, request)
        conv = s.exec(
            select(Conversation).where(Conversation.business_id == b.id, Conversation.channel == "console", Conversation.chat_id == TRY_CHAT_ID)
        ).first()
        messages = (
            s.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()[-40:] if conv else []
        )
    return _render(request, "try.html", "try", b, messages=messages)


@router.post("/panel/try")
def try_send(request: Request, text: str = Form(""), csrf: str = Form("")):
    _check_csrf(request, csrf)
    text = text.strip()[:1000]
    if not text:
        return _back("/panel/try")
    with new_session() as s:
        b = _business(s, request)
        since = utcnow() - timedelta(days=1)
        used = s.exec(
            select(func.count()).select_from(Message).join(Conversation, Message.conversation_id == Conversation.id)
            .where(Message.business_id == b.id, Conversation.channel == "console", Message.role == "customer", Message.created_at >= since)
        ).one()
        if used >= TRY_DAILY_LIMIT:
            _flash(request, f"В тестовом чате не больше {TRY_DAILY_LIMIT} сообщений в сутки. Подключите Telegram и проверьте там.", "error")
            return _back("/panel/try")
        incoming = IncomingMessage("console", TRY_CHAT_ID, "command" if text.startswith("/") else "text", text, "Тест",
                                   f"console:{TRY_CHAT_ID}:{secrets.token_hex(6)}")
        try:
            outcome = handle_incoming(s, b, incoming, _rt(request).get_llm, base_url=_base_url(request),
                                       get_altegio=_rt(request).altegio)
            s.commit()
        except Exception:
            s.rollback()
            log.exception("Test chat failed for %s", b.slug)
            _flash(request, "ИИ сейчас недоступен. Попробуйте через минуту.", "error")
            return _back("/panel/try")
    if outcome.skipped == "subscription":
        _flash(request, "Пробный период закончился — оплатите подписку, чтобы ИИ отвечал.", "error")
    elif outcome.skipped == "bot_disabled":
        _flash(request, "ИИ выключен в настройках.", "error")
    for note in outcome.admin_notes:
        _flash(request, "Уведомление администратору: " + note.splitlines()[0])
    return _back("/panel/try#end")


@router.post("/panel/try/reset")
def try_reset(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    with new_session() as s:
        b = _business(s, request)
        conv = s.exec(
            select(Conversation).where(Conversation.business_id == b.id, Conversation.channel == "console", Conversation.chat_id == TRY_CHAT_ID)
        ).first()
        if conv:
            conv.chat_id = f"{TRY_CHAT_ID}-{secrets.token_hex(4)}"  # keep the history for stats, start a fresh chat
            s.add(conv)
            s.commit()
    return _back("/panel/try")


# --- billing (business side) ---------------------------------------------------------------------------


@router.get("/panel/billing")
def billing_page(request: Request):
    settings = _settings(request)
    now = utcnow()
    with new_session() as s:
        b = _business(s, request)
        sub = billing.get_subscription(s, b.id)
        payments = s.exec(select(Payment).where(Payment.business_id == b.id).order_by(Payment.id.desc())).all()[:12]
    return _render(
        request, "billing.html", "billing", b,
        sub=sub, st=billing.state(sub, now) if sub else None, price=billing.price_for(sub, settings.price_som),
        payments=payments, card=bool(settings.freedompay_merchant_id and settings.freedompay_secret_key),
        instructions=settings.billing_instructions,
    )


@router.post("/panel/billing/pay")
def billing_pay(request: Request, method: str = Form("card"), csrf: str = Form("")):
    _check_csrf(request, csrf)
    settings = _settings(request)
    with new_session() as s:
        b = _business(s, request)
        sub = billing.get_subscription(s, b.id)
        price = billing.price_for(sub, settings.price_som)
        if price <= 0:
            _flash(request, "Цена ещё не назначена. Напишите нам — подключим вручную.", "error")
            return _back("/panel/billing")
        card = method == "card" and settings.freedompay_merchant_id and settings.freedompay_secret_key
        payment = Payment(business_id=b.id, amount_som=price, method="freedompay" if card else "manual")
        s.add(payment)
        s.commit()
        if not card:
            _flash(request, f"Заявка на оплату №{payment.id} создана. Оплатите по реквизитам ниже — подписка продлится после подтверждения.")
            return _back("/panel/billing")
        base = settings.public_base_url
        params = billing.fp_init_params(
            merchant_id=settings.freedompay_merchant_id, secret_key=settings.freedompay_secret_key, payment=payment,
            description=f"Joop AI, подписка 30 дней: {b.name}"[:250], currency=settings.freedompay_currency,
            result_url=f"{base}/billing/freedompay/result", success_url=f"{base}/panel/billing?paid=1",
            failure_url=f"{base}/panel/billing?failed=1", testing=settings.freedompay_testing,
        )
    try:
        r = _rt(request).http.post(f"{settings.freedompay_api_base}/init_payment.php", data=params)
        data = billing.fp_parse_response(r.text)
    except Exception:
        log.exception("FreedomPay init failed")
        data = {}
    if data.get("pg_status") != "ok" or not data.get("pg_redirect_url"):
        _flash(request, "Платёжная система не ответила. Попробуйте позже или оплатите переводом.", "error")
        return _back("/panel/billing")
    with new_session() as s:
        p = s.get(Payment, payment.id)
        p.provider_payment_id = data.get("pg_payment_id", "")
        s.add(p)
        s.commit()
    return RedirectResponse(data["pg_redirect_url"], status_code=303)


@router.post("/billing/freedompay/result")
async def freedompay_result(request: Request):
    """FreedomPay calls this after a card payment. Signed with the store's secret key."""
    settings = _settings(request)
    if not settings.freedompay_secret_key:
        raise HTTPException(status_code=404)
    params = {k: str(v) for k, v in (await request.form()).items()}
    script = "result"
    if not billing.fp_verify(script, params, settings.freedompay_secret_key):
        log.warning("FreedomPay callback with a bad signature")
        raise HTTPException(status_code=403)
    status, text = "ok", "Принято"
    with new_session() as s:
        payment = s.get(Payment, int(params.get("pg_order_id", "0") or 0)) if params.get("pg_order_id", "").isdigit() else None
        if payment is None:
            status, text = "error", "Неизвестный заказ"
        elif params.get("pg_result") == "1":
            if str(payment.amount_som) not in {params.get("pg_amount", ""), params.get("pg_amount", "").split(".")[0]}:
                status, text = "error", "Сумма не совпадает"
            else:
                payment.provider_payment_id = params.get("pg_payment_id", payment.provider_payment_id)
                billing.mark_paid(s, payment, utcnow())
        else:
            if payment.status == "pending":
                payment.status = "failed"
                s.add(payment)
        s.commit()
    body = billing.fp_reply(script, status, text, settings.freedompay_secret_key)
    return Response(body, media_type="application/xml")


# --- founder console ----------------------------------------------------------------------------------


class OwnerRequired(Exception):
    pass


def _owner(request: Request) -> None:
    if not _settings(request).owner_password or request.session.get("owner") is not True:
        raise OwnerRequired


def _owner_render(request: Request, template: str, **ctx: Any):
    ctx.update(request=request, csrf=_csrf(request), flashes=request.session.pop("flash", []), business=None)
    return templates.TemplateResponse(request, template, ctx)


@router.get("/owner/login")
def owner_login_form(request: Request):
    if not _settings(request).owner_password:
        raise HTTPException(status_code=404)
    return _owner_render(request, "owner_login.html")


@router.post("/owner/login")
def owner_login(request: Request, password: str = Form(""), csrf: str = Form("")):
    expected = _settings(request).owner_password
    if not expected:
        raise HTTPException(status_code=404)
    _check_csrf(request, csrf)
    from .app import record_failure, throttled  # counted in memory, not in the cookie a guesser can drop

    now = time.time()
    if throttled("owner!", request, now):
        _flash(request, "Слишком много попыток. Подождите 15 минут.", "error")
        return _back("/owner/login")
    if not hmac.compare_digest(password.encode(), expected.encode()):
        record_failure("owner!", request, now)
        _flash(request, "Неверный пароль.", "error")
        return _back("/owner/login")
    request.session.clear()
    request.session["owner"] = True
    return _back("/owner")


@router.post("/owner/logout")
def owner_logout(request: Request, csrf: str = Form("")):
    _check_csrf(request, csrf)
    request.session.clear()
    return _back("/owner/login")


def _counts(s: Session, model: Any, since) -> dict[int, int]:
    rows = s.exec(select(model.business_id, func.count()).where(model.created_at >= since).group_by(model.business_id)).all()
    return {bid: n for bid, n in rows}


@router.get("/owner")
def owner_home(request: Request):
    _owner(request)
    settings = _settings(request)
    now = utcnow()
    since = now - timedelta(days=30)
    with new_session() as s:
        businesses = s.exec(select(Business).where(Business.slug.not_like("site-demo-%")).order_by(Business.id.desc())).all()
        subs = {x.business_id: x for x in s.exec(select(Subscription)).all()}
        msgs = _counts(s, Message, since)
        bookings = _counts(s, Booking, since)
        leads = _counts(s, Lead, since)
        orders = _counts(s, Order, since)
        cost_rows = s.exec(
            select(Message.business_id, func.coalesce(func.sum(Message.cost_usd), 0.0)).where(Message.created_at >= since).group_by(Message.business_id)
        ).all()
        cost = {bid: float(c) for bid, c in cost_rows}
        pending = s.exec(select(Payment).where(Payment.status == "pending").order_by(Payment.id.desc())).all()
        paid30 = s.exec(select(func.coalesce(func.sum(Payment.amount_som), 0)).where(Payment.status == "paid", Payment.paid_at >= since)).one()
        mrr = billing.mrr(s, now, settings.price_som)
    rows = []
    counts = {"trial": 0, "active": 0, "grace": 0, "expired": 0, "suspended": 0, "none": 0}
    for b in businesses:
        sub = subs.get(b.id)
        st = billing.state(sub, now) if sub else None
        counts[st.code if st else "none"] += 1
        rows.append({
            "b": b, "sub": sub, "st": st, "pack": get_pack(b.niche).label,
            "msgs": msgs.get(b.id, 0), "results": bookings.get(b.id, 0) + leads.get(b.id, 0) + orders.get(b.id, 0),
            "cost": cost.get(b.id, 0.0), "price": billing.price_for(sub, settings.price_som),
        })
    names = {b.id: b.name for b in businesses}
    from .. import health
    from .demo import funnel, recent_questions

    with new_session() as s:
        site = funnel(s, since)
        asked = recent_questions(s, since)
        ai = health.status(s, now)
    return _owner_render(request, "owner.html", rows=rows, counts=counts, mrr=mrr, paid30=paid30, pending=pending,
                         names=names, price=settings.price_som, trial_days=settings.trial_days,
                         total_cost=sum(cost.values()), site=site, asked=asked, ai=ai, alerts_on=bool(settings.founder_bot_token and settings.founder_chat_id))


@router.post("/owner/business/{bid}")
def owner_business_action(
    request: Request, bid: int, action: str = Form(""), days: int = Form(0), price: int = Form(0), note: str = Form(""),
    csrf: str = Form(""),
):
    _owner(request)
    _check_csrf(request, csrf)
    settings = _settings(request)
    now = utcnow()
    with new_session() as s:
        b = s.get(Business, bid)
        if b is None:
            raise HTTPException(status_code=404)
        sub = billing.get_subscription(s, bid) or Subscription(business_id=bid, source="owner", status="trial", trial_ends_at=now)
        if action == "extend":
            base = sub.trial_ends_at if sub.trial_ends_at and sub.trial_ends_at > now else now
            sub.trial_ends_at = base + timedelta(days=max(1, min(days or 7, 90)))
            sub.status = "trial" if sub.status != "active" else sub.status
            msg = f"{b.name}: пробный период до {sub.trial_ends_at:%d.%m.%Y}."
        elif action == "paid":
            amount = billing.price_for(sub, settings.price_som)
            if amount <= 0:
                _flash(request, "Сначала задайте цену.", "error")
                return _back("/owner")
            s.add(sub)
            s.flush()
            pay = Payment(business_id=bid, amount_som=amount, method="manual")
            s.add(pay)
            s.flush()
            billing.mark_paid(s, pay, now)
            msg = f"{b.name}: оплата {amount} сом отмечена, оплачено до {sub.paid_until:%d.%m.%Y}."
        elif action == "suspend":
            sub.status = "suspended"
            msg = f"{b.name}: ИИ приостановлен."
        elif action == "resume":
            sub.status = "active" if sub.paid_until and sub.paid_until > now else "trial"
            msg = f"{b.name}: ИИ снова работает."
        elif action == "price":
            sub.price_som = max(0, price)
            msg = f"{b.name}: цена {sub.price_som or settings.price_som} сом в месяц."
        elif action == "note":
            sub.note = note.strip()[:500]
            msg = "Заметка сохранена."
        elif action == "login":
            request.session["bid"] = bid  # the founder opens the business's panel to help with setup
            return _back("/panel/setup")
        else:
            raise HTTPException(status_code=400)
        s.add(sub)
        s.commit()
    _flash(request, msg)
    return _back("/owner")


@router.post("/owner/payment/{pid}")
def owner_payment_action(request: Request, pid: int, action: str = Form(""), csrf: str = Form("")):
    _owner(request)
    _check_csrf(request, csrf)
    with new_session() as s:
        p = s.get(Payment, pid)
        if p is None:
            raise HTTPException(status_code=404)
        if action == "confirm":
            billing.mark_paid(s, p, utcnow())
            _flash(request, f"Оплата №{p.id} подтверждена.")
        elif action == "reject":
            p.status = "failed"
            s.add(p)
            _flash(request, f"Оплата №{p.id} отклонена.")
        s.commit()
    return _back("/owner")


# --- sales pipeline ---------------------------------------------------------------------------------------

SALES_WRITER = """You write the first message from Bektur, founder of Joop AI, to a small business in Kyrgyzstan.
Joop AI is an AI administrator: it answers customers in Telegram, WhatsApp and Instagram 24/7 in Kyrgyz and
Russian, takes bookings and orders from the business's own price list, and passes complaints to a human.
Rules:
- Language: {language}. Kyrgyz must be natural Kyrgyz in Cyrillic; Russian plain and polite.
- 3-5 short sentences, like a real person writing in WhatsApp. No markdown, no emoji, no exclamation spam.
- Open with one specific detail about this business from the notes, if there is one. Never invent facts,
  numbers, reviews or results. Do not promise anything that is not in the description above.
- One concrete benefit for this kind of business ({niche}), for example answers at night or on weekends.
- Offer a free {trial_days}-day trial set up by the founder, and end with one easy question.
- Mention that they can try a demo bot first if a demo link is given.
Output only the message text."""

SITE_OFFER_WRITER = """You write the first message from Bektur of Joop Studio to a small business in Kyrgyzstan
that may not have a website. Joop Studio makes a one-page website, an online menu or price list, or slides in 1-2 days
from what the owner sends, and can add a booking button handled by the Joop AI administrator.
Rules:
- Language: {language}. Kyrgyz must be natural Kyrgyz in Cyrillic; Russian plain and polite.
- 3-5 short sentences, like a real person writing in WhatsApp. No markdown, no emoji.
- Open with one specific detail from the notes, if there is one. Never invent facts, prices, numbers or results,
  and do not claim they have no website unless the notes say so.
- One concrete benefit for this kind of business ({niche}), e.g. customers find prices and address without calling.
- Offer to send a free draft first, and end with one easy question.
Output only the message text."""


def draft_message(llm: Any, p: Prospect, trial_days: int, demo_link: str = "", offer: str = "agent") -> str | None:
    writer = getattr(llm, "write", None)
    if writer is None:
        return None
    template = SITE_OFFER_WRITER if offer == "site" else SALES_WRITER
    instruction = template.format(
        language="Kyrgyz" if p.language == "ky" else "Russian", niche=get_pack(p.niche).label, trial_days=trial_days
    )
    facts = "\n".join(f"{k}: {v}" for k, v in (
        ("Business", p.name), ("Type", get_pack(p.niche).label), ("City", p.city), ("Contact person", p.contact_name),
        ("Instagram", p.instagram), ("Notes", p.notes), ("Demo link", demo_link),
    ) if v)
    return writer(instruction, facts, empty_usage())


PILOT_DEFAULT_DAYS = 14
PILOT_TZ = "Asia/Bishkek"


def _pilot_period(request: Request) -> tuple[str, str, Any, Any]:
    """Local dates from the query (YYYY-MM-DD, both inclusive) and the UTC bounds [since, until)."""
    from datetime import date, datetime as dt

    from ..timeutil import local_now, local_to_utc

    today = local_now(PILOT_TZ).date()

    def parse(name: str, default: date) -> date:
        try:
            return date.fromisoformat(request.query_params.get(name, "")[:10])
        except ValueError:
            return default

    end = parse("until", today)
    start = parse("since", end - timedelta(days=PILOT_DEFAULT_DAYS - 1))
    if start > end:
        start, end = end, start
    since = local_to_utc(dt.combine(start, dt.min.time()), PILOT_TZ)
    until = local_to_utc(dt.combine(end + timedelta(days=1), dt.min.time()), PILOT_TZ)
    return start.isoformat(), end.isoformat(), since, until


@router.get("/owner/pilot")
def owner_pilot(request: Request):
    from .. import pilot

    _owner(request)
    start, end, since, until = _pilot_period(request)
    with new_session() as s:
        rows, total = pilot.report(s, since, until, utcnow())
    return _owner_render(request, "owner_pilot.html", rows=rows, total=total, since=start, until=end)


@router.get("/owner/pilot.csv")
def owner_pilot_csv(request: Request):
    from .. import pilot

    _owner(request)
    start, end, since, until = _pilot_period(request)
    with new_session() as s:
        rows, total = pilot.report(s, since, until, utcnow())
    return Response(pilot.to_csv(rows, total), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="joop-pilot-{start}-{end}.csv"'})


@router.get("/owner/prospects")
def prospects_page(request: Request, status: str = ""):
    _owner(request)
    with new_session() as s:
        q = select(Prospect).order_by(Prospect.updated_at.desc())
        if status in PROSPECT_STATUSES:
            q = q.where(Prospect.status == status)
        items = s.exec(q).all()
        counts = dict(s.exec(select(Prospect.status, func.count()).group_by(Prospect.status)).all())
    return _owner_render(request, "owner_prospects.html", items=items, counts=counts, statuses=PROSPECT_STATUSES,
                         packs=all_packs(), current=status, base=_settings(request).public_base_url)


def _prospect_from(row: dict[str, str]) -> Prospect | None:
    name = (row.get("name") or row.get("название") or "").strip()
    if not name:
        return None
    niche = (row.get("niche") or row.get("ниша") or "other").strip()
    return Prospect(
        name=name[:120], niche=niche if niche in all_packs() else "other",
        city=(row.get("city") or row.get("город") or "Бишкек").strip()[:60],
        contact_name=(row.get("contact") or row.get("контакт") or "").strip()[:80],
        phone=(row.get("phone") or row.get("телефон") or "").strip()[:40],
        instagram=(row.get("instagram") or "").strip().lstrip("@")[:60],
        notes=(row.get("notes") or row.get("заметки") or "").strip()[:500],
        language="ky" if (row.get("language") or row.get("язык") or "").strip().lower() in {"ky", "кыргызча", "кырг"} else "ru",
    )


@router.post("/owner/prospects")
def prospects_add(
    request: Request, name: str = Form(""), niche: str = Form("other"), phone: str = Form(""), instagram: str = Form(""),
    contact: str = Form(""), notes: str = Form(""), language: str = Form("ru"), csv_text: str = Form(""), csrf: str = Form(""),
):
    _owner(request)
    _check_csrf(request, csrf)
    added = 0
    with new_session() as s:
        if csv_text.strip():
            reader = csv.DictReader(io.StringIO(csv_text.strip()))
            for row in reader:
                p = _prospect_from({(k or "").strip().lower(): (v or "") for k, v in row.items()})
                if p:
                    s.add(p)
                    added += 1
        else:
            p = _prospect_from({"name": name, "niche": niche, "phone": phone, "instagram": instagram, "contact": contact,
                                "notes": notes, "language": language})
            if p:
                s.add(p)
                added = 1
        s.commit()
    _flash(request, f"Добавлено: {added}." if added else "Нечего добавлять: нужно хотя бы название.", "ok" if added else "error")
    return _back("/owner/prospects")


@router.post("/owner/prospects/{pid}")
def prospect_action(request: Request, pid: int, action: str = Form(""), status: str = Form(""), message: str = Form(""),
                    csrf: str = Form("")):
    _owner(request)
    _check_csrf(request, csrf)
    settings = _settings(request)
    now = utcnow()
    with new_session() as s:
        p = s.get(Prospect, pid)
        if p is None:
            raise HTTPException(status_code=404)
        if action == "status" and status in PROSPECT_STATUSES:
            p.status = status
        elif action == "save":
            p.message = message.strip()[:2000]
        elif action == "demo":
            if p.demo_business_id is None:
                password = secrets.token_urlsafe(9)
                b = create_business(s, slug=unique_slug(s, p.name), name=p.name, password=password, niche=p.niche, demo=True, now_utc=now)
                billing.start_trial(s, b, settings.trial_days, now, "prospect", p.contact_name, p.phone)
                p.demo_business_id = b.id
                p.status = "demo" if p.status in {"new", "contacted", "replied"} else p.status
                _flash(request, f"Демо создано. Логин: {b.slug}, пароль: {password} (покажется один раз).")
            else:
                _flash(request, "Демо уже есть.", "error")
        elif action in {"draft", "draft_site"}:
            demo_link = ""
            if p.demo_business_id and settings.public_base_url:
                demo_link = f"{settings.public_base_url}/login"
            try:
                text = draft_message(_rt(request).get_llm(), p, settings.trial_days, demo_link,
                                     offer="site" if action == "draft_site" else "agent")
            except Exception:
                log.exception("Sales draft failed")
                text = None
            if text:
                p.message = text.strip()
                _flash(request, "Черновик готов. Проверьте, поправьте и отправьте сами.")
            else:
                _flash(request, "ИИ не смог написать черновик. Проверьте ANTHROPIC_API_KEY.", "error")
        elif action == "delete":
            s.delete(p)
            s.commit()
            return _back("/owner/prospects")
        else:
            raise HTTPException(status_code=400)
        p.updated_at = now
        s.add(p)
        s.commit()
    return _back(f"/owner/prospects#p{pid}")


# --- partners (referral program) ------------------------------------------------------------------


@router.get("/r/{code}")
def referral_link(request: Request, code: str):
    """Short link a partner shares: remembers the partner and opens the landing page."""
    with new_session() as s:
        if partners.find_active(s, code):
            request.session["ref"] = code.strip().lower()
    return RedirectResponse("/", status_code=303)


@router.get("/partner/{secret}")
def partner_page(request: Request, secret: str):
    """The partner's own page: their link, businesses they brought, money earned. The URL is the password."""
    if len(secret) < 16:
        raise HTTPException(status_code=404)
    with new_session() as s:
        partner = s.exec(select(Partner).where(Partner.secret == secret)).first()
        if partner is None:
            raise HTTPException(status_code=404)
        st = partners.stats(s, partner, utcnow())
    base = _settings(request).public_base_url
    return _owner_render(request, "partner.html", st=st, link=f"{base}/r/{partner.code}" if base else f"/r/{partner.code}",
                         price=_settings(request).price_som)


@router.get("/owner/partners")
def owner_partners(request: Request):
    _owner(request)
    now = utcnow()
    with new_session() as s:
        items = [partners.stats(s, p, now) for p in s.exec(select(Partner).order_by(Partner.id.desc())).all()]
    return _owner_render(request, "owner_partners.html", items=items, base=_settings(request).public_base_url)


@router.post("/owner/partners")
def owner_partner_add(request: Request, name: str = Form(""), phone: str = Form(""), percent: int = Form(20),
                      code: str = Form(""), csrf: str = Form("")):
    _owner(request)
    _check_csrf(request, csrf)
    if len(name.strip()) < 2:
        _flash(request, "Укажите имя партнёра.", "error")
        return _back("/owner/partners")
    with new_session() as s:
        p = partners.new_partner(s, name, phone, percent, code)
        s.commit()
        _flash(request, f"Партнёр добавлен. Ссылка: /r/{p.code}. Личная страница партнёра: /partner/{p.secret} — отправьте её ему.")
    return _back("/owner/partners")


@router.post("/owner/partners/{pid}")
def owner_partner_action(request: Request, pid: int, action: str = Form(""), amount: int = Form(0), note: str = Form(""),
                         csrf: str = Form("")):
    _owner(request)
    _check_csrf(request, csrf)
    with new_session() as s:
        p = s.get(Partner, pid)
        if p is None:
            raise HTTPException(status_code=404)
        if action == "payout" and amount > 0:
            s.add(PartnerPayout(partner_id=pid, amount_som=amount, note=note.strip()[:200]))
            _flash(request, f"Выплата {amount} сом партнёру {p.name} записана.")
        elif action == "toggle":
            p.active = not p.active
            s.add(p)
            _flash(request, f"{p.name}: {'активен' if p.active else 'отключён'}.")
        else:
            raise HTTPException(status_code=400)
        s.commit()
    return _back("/owner/partners")
