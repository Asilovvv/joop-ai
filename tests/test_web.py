import hashlib
import hmac
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Lead, Service, Slot, Staff
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM, first_free_slot


@pytest.fixture
def client(settings, rt, business):
    app = create_app(settings, rt, init=False)
    with TestClient(app) as c:
        yield c


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "no csrf token on page"
    return match.group(1)


def login(client) -> str:
    token = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"slug": "aktish", "password": "secret-pass", "csrf": token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/panel"
    return csrf_of(client.get("/panel").text)


def test_login_required_and_wrong_password(client):
    r = client.get("/panel", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    token = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"slug": "aktish", "password": "nope", "csrf": token})
    assert "Неверный логин или пароль" in r.text
    r = client.post("/login", data={"slug": "aktish", "password": "secret-pass", "csrf": "forged"})
    assert r.status_code == 403


def test_all_pages_render(client, business):
    login(client)
    expected = {
        "/panel": "Последние 14 дней",
        "/panel/services": "Профессиональная чистка",
        "/panel/staff": "Нурлан Абдыкадыров",
        "/panel/faq": "Есть ли парковка?",
        "/panel/slots": "Заполнить по графику",
        "/panel/bookings": "Предстоящие",
        "/panel/leads": "Новых заявок нет",
        "/panel/conversations": "Диалогов пока нет",
        "/panel/settings": f"/admin {business.admin_link_code}",
        "/panel/channels": "Токены хранятся на сервере",
    }
    for url, text in expected.items():
        r = client.get(url)
        assert r.status_code == 200, url
        assert text in r.text, url


def test_price_list_crud(client, business):
    token = login(client)
    client.post("/panel/services", data={"name": "Отбеливание", "price": "8 000", "note": "", "csrf": token})
    with db.new_session() as s:
        row = s.exec(select(Service).where(Service.name == "Отбеливание")).one()
    client.post(f"/panel/services/{row.id}", data={"name": "Отбеливание Zoom", "price": "9 000", "note": "1 сеанс", "csrf": token})
    with db.new_session() as s:
        assert s.get(Service, row.id).price == "9 000"
    client.post(f"/panel/services/{row.id}/delete", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(Service, row.id) is None
    assert client.post("/panel/services", data={"name": "X", "csrf": "bad"}).status_code == 403


def test_slots_generate_add_toggle_delete(client, business):
    token = login(client)
    with db.new_session() as s:
        new = Staff(business_id=business.id, name="Тимур Асанов", role="ортодонт")
        s.add(new)
        s.commit()
        staff_id = new.id
    client.post(
        "/panel/slots/generate",
        data={"staff_id": staff_id, "date_from": "2026-11-09", "date_to": "2026-11-15", "start": "10:00", "end": "13:00", "step": 60, "csrf": token},
    )
    with db.new_session() as s:
        rows = s.exec(select(Slot).where(Slot.staff_id == staff_id)).all()
    # Mon 9 .. Sat 14 (Sunday off) x 10:00, 11:00, 12:00
    assert len(rows) == 18
    client.post("/panel/slots/add", data={"staff_id": staff_id, "day": "2026-11-16", "times": "15:00, 16.30", "csrf": token})
    with db.new_session() as s:
        assert len(s.exec(select(Slot).where(Slot.staff_id == staff_id)).all()) == 20
    target = rows[0].id
    client.post(f"/panel/slots/{target}/toggle", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(Slot, target).status == "booked"
    client.post(f"/panel/slots/{target}/delete", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(Slot, target) is None


def test_cancel_booking_frees_slot_and_pause(client, business):
    token = login(client)
    slot = first_free_slot(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        llm = FakeLLM([AgentReply("Записала", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "service": "осмотр"})])
        out = handle_incoming(s, b, IncomingMessage("telegram", "1001", "text", "запишите", "Айбек", "x1"), lambda: llm, NOW_UTC)
        s.commit()
    assert "Айбек" in client.get("/panel/bookings").text
    client.post(f"/panel/bookings/{out.booking_id}/cancel", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(Booking, out.booking_id).status == "cancelled"
        assert s.get(Slot, slot.id).status == "free"
        conv_id = s.exec(select(Conversation)).one().id
    page = client.get(f"/panel/conversations/{conv_id}").text
    assert "Выключить ИИ на 24 часа" in page and "Записала" in page
    client.post(f"/panel/conversations/{conv_id}/pause", data={"hours": 24, "csrf": token})
    assert "Включить ИИ" in client.get(f"/panel/conversations/{conv_id}").text
    client.post(f"/panel/conversations/{conv_id}/resume", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(Conversation, conv_id).ai_paused_until is None


def test_settings_and_channels(client, business):
    token = login(client)
    r = client.post(
        "/panel/settings",
        data={
            "csrf": token, "name": "Ак-Тиш Дент", "address": "Бишкек", "phone": "+996555000000", "hours_text": "Пн–Пт",
            "work_start": "10:00", "work_end": "20:00", "off6": "1", "off7": "1", "timezone": "Asia/Bishkek",
            "extra_rules": "Рассрочка только на импланты", "greeting": "", "reminder_hour": "17", "digest_hour": "9",
        },
    )
    assert r.status_code == 200
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.work_start, b.work_end, b.days_off, b.reminder_hour, b.bot_enabled) == ("10:00", "20:00", "6,7", 17, False)

    client.post(
        "/panel/channels",
        data={"csrf": token, "telegram_bot_token": "", "wa_phone_number_id": "pn-1", "wa_access_token": "EAAG-secret-token",
              "wa_reminder_template": "appointment_reminder", "wa_template_lang": "ru", "ig_account_id": "ig-1", "ig_access_token": ""},
    )
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert b.telegram_bot_token == "123:TEST"  # empty field keeps the existing token
        assert b.wa_access_token == "EAAG-secret-token" and b.wa_phone_number_id == "pn-1"
    page = client.get("/panel/channels").text
    assert "EAAG-secret-token" not in page and "123:TEST" not in page

    old_code = business.admin_link_code
    client.post("/panel/settings/link-code", data={"csrf": token})
    with db.new_session() as s:
        assert s.get(Business, business.id).admin_link_code != old_code


def test_telegram_webhook(client, rt, business):
    update = {"update_id": 1, "message": {"message_id": 5, "chat": {"id": 1001, "type": "private"}, "from": {"id": 1001, "first_name": "Айбек"}, "text": "Здравствуйте"}}
    assert client.post("/webhooks/telegram/aktish", json=update).status_code == 403
    r = client.post("/webhooks/telegram/aktish", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": business.telegram_secret})
    assert r.status_code == 200
    assert rt.tg.sent == [("1001", "Здравствуйте! Чем помочь?")]
    # Telegram retries the same update: no second reply.
    client.post("/webhooks/telegram/aktish", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": business.telegram_secret})
    assert len(rt.tg.sent) == 1


def _signed(body: dict, secret: str = "app-secret") -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def test_meta_verify_and_signature(client):
    ok = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"}).status_code == 403
    raw, headers = _signed({"object": "whatsapp_business_account", "entry": []}, secret="wrong")
    assert client.post("/webhooks/meta", content=raw, headers=headers).status_code == 403


def test_whatsapp_and_instagram_webhooks(client, rt, business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.wa_phone_number_id, b.wa_access_token = "pn-1", "tok"
        b.ig_account_id, b.ig_access_token = "ig-1", "tok"
        s.commit()

    wa = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "pn-1"},
            "contacts": [{"wa_id": "996555000111", "profile": {"name": "Айгуль"}}],
            "messages": [
                {"from": "996555000111", "id": "wamid.1", "type": "text", "text": {"body": "Здравствуйте"}},
                {"from": "996555000111", "id": "wamid.2", "type": "text", "text": {"body": "сколько стоит чистка?"}},
            ],
        }}]}],
    }
    raw, headers = _signed(wa)
    assert client.post("/webhooks/meta", content=raw, headers=headers).text == "EVENT_RECEIVED"
    assert rt.wa.sent == [("996555000111", "Здравствуйте! Чем помочь?")]
    first_call = rt._llm.calls[0]["messages"]
    assert first_call == [{"role": "user", "content": "Здравствуйте\nсколько стоит чистка?"}]

    voice = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "pn-1"},
            "messages": [{"from": "996555000111", "id": "wamid.3", "type": "audio", "audio": {"id": "m1", "voice": True}}],
        }}]}],
    }
    raw, headers = _signed(voice)
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert "Я пока понимаю только текстовые сообщения" in rt.wa.sent[-1][1]

    ig = {"object": "instagram", "entry": [{"id": "ig-1", "time": 1, "messaging": [
        {"sender": {"id": "igsid-9"}, "recipient": {"id": "ig-1"}, "timestamp": 1, "message": {"mid": "m-1", "text": "Есть запись на завтра?"}}
    ]}]}
    raw, headers = _signed(ig)
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert rt.ig.sent == [("igsid-9", "Здравствуйте! Чем помочь?")]

    staff_echo = {"object": "instagram", "entry": [{"id": "ig-1", "time": 2, "messaging": [
        {"sender": {"id": "ig-1"}, "recipient": {"id": "igsid-9"}, "timestamp": 2, "message": {"mid": "m-2", "text": "Перезвоню вам", "is_echo": True}}
    ]}]}
    raw, headers = _signed(staff_echo)
    client.post("/webhooks/meta", content=raw, headers=headers)
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.channel == "instagram")).one()
        assert conv.ai_paused_until is not None
        assert s.exec(select(Lead).where(Lead.kind == "media")).one()


def test_customer_text_is_escaped_in_panel(client, business):
    login(client)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        llm = FakeLLM([AgentReply("Ок")])
        handle_incoming(s, b, IncomingMessage("telegram", "666", "text", "<script>alert(1)</script>", "<b>x</b>", "xss"), lambda: llm, NOW_UTC)
        s.commit()
        conv_id = s.exec(select(Conversation).where(Conversation.chat_id == "666")).one().id
    listing = client.get("/panel/conversations").text
    assert "<b>x</b>" not in listing and "&lt;b&gt;x&lt;/b&gt;" in listing
    detail = client.get(f"/panel/conversations/{conv_id}").text
    assert "<script>alert(1)</script>" not in detail and "&lt;script&gt;" in detail


def test_kyrgyz_name_and_profile_texts_saved(client, business):
    token = login(client)
    client.post("/panel/services", data={"name": "Отбеливание", "name_ky": "Тишти агартуу", "price": "8 000", "note": "", "csrf": token})
    with db.new_session() as s:
        assert s.exec(select(Service).where(Service.name == "Отбеливание")).one().name_ky == "Тишти агартуу"
    client.post("/panel/settings", data={
        "csrf": token, "name": "Ак-Тиш Дент", "work_start": "09:00", "work_end": "19:00", "timezone": "Asia/Bishkek",
        "description": "Частная клиника", "booking_policy": "Администратор перезванивает", "tone": "На «вы»",
        "bot_enabled": "1", "reminder_hour": "18", "digest_hour": "8",
    })
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.description, b.booking_policy, b.tone) == ("Частная клиника", "Администратор перезванивает", "На «вы»")
    assert "расход на ИИ" in client.get("/panel").text


def test_public_pages(settings, rt, business):
    import dataclasses

    app = create_app(dataclasses.replace(settings, company_legal_name="ИП Асилов Б.", contact_email="hi@joop.kg", contact_telegram="joop_kg"), rt, init=False)
    with TestClient(app) as c:
        home = c.get("/")
        assert home.status_code == 200 and "Попробовать 14 дней бесплатно" in home.text
        assert "ИП Асилов Б." in home.text and "@joop_kg" in home.text
        privacy = c.get("/privacy").text
        assert "Anthropic" in privacy and "ИП Асилов Б." in privacy and "hi@joop.kg" in privacy
        assert "в течение 30 дней" in c.get("/data-deletion").text
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert "Контакты появятся здесь" in c.get("/").text


def test_restaurant_panel(settings, rt, engine):
    from joop.agent.engine import handle_incoming as handle
    from joop.models import Order
    from joop.presets import create_business as create

    with db.new_session() as s:
        b = create(s, slug="cafe", name="Кафе", password="secret-pass", niche="restaurant", demo=True, now_utc=NOW_UTC)
        s.commit()
        plov = s.exec(select(Service).where(Service.business_id == b.id, Service.name == "Плов")).one()
        llm = FakeLLM([AgentReply("Готово.", order={"lines": [{"item_id": plov.id, "quantity": 2, "note": ""}], "mode": "delivery",
                                                     "address": "Киевская 1", "time": "", "name": "Айбек", "phone": "0555123456", "comment": ""})])
        out = handle(s, b, IncomingMessage("telegram", "1", "text", "2 плова", "", "ord"), lambda: llm, NOW_UTC)
        s.commit()
    app = create_app(settings, rt, init=False)
    with TestClient(app) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "cafe", "password": "secret-pass", "csrf": token})
        token = csrf_of(c.get("/panel").text)
        panel = c.get("/panel").text
        assert "Заказы" in panel and "Меню" in panel and "Столы" in panel and "заказов принял ИИ" in panel
        orders = c.get("/panel/orders").text
        assert "2 × Плов" in orders and "850 сом" in orders and "доставка 150" in orders and "Киевская 1" in orders
        c.post(f"/panel/orders/{out.order_id}/status", data={"status": "accepted", "csrf": token})
        with db.new_session() as s:
            assert s.get(Order, out.order_id).status == "accepted"
        # stop list and price value
        c.post(f"/panel/services/{plov.id}", data={"name": "Плов", "name_ky": "Палоо", "price": "380", "note": "", "csrf": token})
        with db.new_session() as s:
            row = s.get(Service, plov.id)
            assert row.available is False and row.price_value == 380
        # table capacity
        c.post("/panel/staff", data={"name": "Стол 9", "role": "VIP", "handles": "", "capacity": "12", "csrf": token})
        with db.new_session() as s:
            from joop.models import Staff
            assert s.exec(select(Staff).where(Staff.name == "Стол 9")).one().capacity == 12
        assert 'name="capacity"' in c.get("/panel/staff").text


def test_wholesale_panel_hides_booking_sections(settings, rt, engine):
    from joop.presets import create_business as create

    with db.new_session() as s:
        create(s, slug="opt", name="Опт", password="secret-pass", niche="wholesale", demo=True, now_utc=NOW_UTC)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "opt", "password": "secret-pass", "csrf": token})
        nav = c.get("/panel").text.split("</aside>")[0]  # the sidebar
        assert "Каталог" in nav and "Заказы" in nav and "Окна" not in nav and "Записи" not in nav


def test_login_is_locked_after_repeated_failures(client):
    from joop.web import app as web_app

    web_app._login_fails.clear()
    token = csrf_of(client.get("/login").text)
    for _ in range(web_app.LOGIN_MAX_FAILS):
        client.post("/login", data={"slug": "aktish", "password": "wrong", "csrf": token})
    r = client.post("/login", data={"slug": "aktish", "password": "secret-pass", "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == "/login"  # correct password is refused while locked
    assert "Слишком много" in client.get("/login").text
    web_app._login_fails.clear()
    login(client)


def test_faq_keeps_the_kyrgyz_wording(client, business):
    from joop.models import Faq

    token = login(client)
    client.post("/panel/faq", data={"question": "Есть Wi-Fi?", "question_ky": "Wi-Fi барбы?", "answer": "Да, бесплатный.", "csrf": token})
    with db.new_session() as s:
        row = s.exec(select(Faq).where(Faq.question == "Есть Wi-Fi?")).one()
    assert row.question_ky == "Wi-Fi барбы?" and 'value="Wi-Fi барбы?"' in client.get("/panel/faq").text
    client.post(f"/panel/faq/{row.id}", data={"question": "Есть Wi-Fi?", "question_ky": "", "answer": "Да.", "csrf": token})
    with db.new_session() as s:
        assert s.get(Faq, row.id).question_ky == ""


def test_dashboard_shows_messages_by_hour(client, business):
    from datetime import timedelta as td

    from joop.models import Conversation, Message
    from joop.stats import by_hour, hour_bars

    from .conftest import NOW_UTC

    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="h1")
        s.add(conv)
        s.flush()
        # Bishkek is UTC+6: 17:00 UTC is 23:00 local (off hours), 05:00 UTC is 11:00 local (working hours)
        for hour, off, n in ((17, True, 3), (5, False, 1)):
            for i in range(n):
                s.add(Message(business_id=business.id, conversation_id=conv.id, role="customer", text="?", off_hours=off,
                              created_at=NOW_UTC.replace(hour=hour, minute=i) - td(days=1)))
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="ai", text="!", created_at=NOW_UTC - td(days=1)))
        s.commit()
        data = by_hour(s, business.id, NOW_UTC - td(days=14), business.timezone)
    assert (data["total"], data["off_total"], data["off_pct"]) == (4, 3, 75)
    assert data["off"][23] == 3 and data["on"][11] == 1
    bars = hour_bars(data)
    assert len(bars) == 24 and bars[23]["off_d"] and not bars[23]["on_d"] and bars[11]["on_d"] and not bars[0]["on_d"]
    assert bars[23]["top"] < bars[11]["top"]  # the taller bar reaches higher
    login(client)
    page = client.get("/panel").text
    assert "Когда пишут клиенты" in page and "<b>75%</b>" in page and "23:00–00:00 — 3 сообщ., из них 3 в нерабочее время" in page
