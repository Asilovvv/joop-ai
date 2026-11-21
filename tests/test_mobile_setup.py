"""The launch checklist in the owner's app: the panel's «Запуск» list, the Telegram bot by its token, booking by
link without a chat — so an owner who signed up on the phone needs no computer for the first customer."""

from sqlmodel import select

from joop import db
from joop.models import Business, PanelUser
from joop.security import hash_password

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

TOKEN = "987654:" + "A" * 35


def _owner(client):
    return auth(sign_in(client).json()["token"])


def test_the_owner_sees_the_panels_launch_list(client, business):
    data = client.get("/api/mobile/setup", headers=_owner(client)).json()
    keys = [step["key"] for step in data["steps"]]
    assert keys[:2] == ["contacts", "prices"] and "telegram" in keys and keys[-1] == "pay"
    prices = next(x for x in data["steps"] if x["key"] == "prices")
    assert prices["panel"] == "https://joop.test/panel/services"
    assert data["telegram"] == {"connected": True, "username": business.telegram_bot_username}
    assert data["page_booking"] == {"available": True, "on": False, "works": False, "why": "page",
                                    "url": "https://joop.test/m/aktish/book"}


def test_the_bot_is_connected_from_the_phone(client, business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token, b.telegram_bot_username = "", ""
        s.add(b)
        s.commit()
    owner = _owner(client)
    r = client.post("/api/mobile/setup/telegram", json={"token": "not a token"}, headers=owner)
    assert r.status_code == 422 and r.json()["error"].startswith("Это не похоже на токен бота")
    r = client.post("/api/mobile/setup/telegram", json={"token": TOKEN}, headers=owner)  # Telegram says no (no getMe)
    assert r.status_code == 422 and "Telegram не принял токен" in r.json()["error"]
    with db.new_session() as s:
        assert s.get(Business, business.id).telegram_bot_token == ""  # an unchecked token is never saved
    rt.tg.me = {"username": "aktish_bot"}
    rt.tg.set_webhook = lambda url, secret: url == "https://joop.test/webhooks/telegram/aktish"
    r = client.post("/api/mobile/setup/telegram", json={"token": f"  {TOKEN} "}, headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["notes"][0] == {"text": "Бот @aktish_bot подключён. Напишите ему — ИИ ответит.", "ok": True}
    assert r.json()["telegram"] == {"connected": True, "username": "aktish_bot"}
    assert next(x for x in r.json()["steps"] if x["key"] == "telegram")["done"] is True
    with db.new_session() as s:
        assert s.get(Business, business.id).telegram_bot_token == TOKEN


def test_booking_by_link_is_turned_on_from_the_phone(client, business):
    r = client.post("/api/mobile/setup/page-booking", json={"on": True}, headers=_owner(client))
    assert r.status_code == 200 and r.json()["page_booking"]["on"] is True and r.json()["page_booking"]["why"] == ""
    assert r.json()["page_booking"]["works"] is True
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.page_booking, b.menu_enabled) == (True, True)  # the public page it lives on opens with it
    r = client.post("/api/mobile/setup/page-booking", json={"on": False}, headers=_owner(client))
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert (b.page_booking, b.menu_enabled) == (False, True) and r.json()["page_booking"]["on"] is False


def test_only_the_owner_changes_the_setup(client, business):
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Айгерим", login="aigerim", password_hash=hash_password("staff-pass-1")))
        s.commit()
    staff = auth(sign_in(client, user="aigerim", password="staff-pass-1").json()["token"])
    for method, path, body in (("get", "/api/mobile/setup", None), ("post", "/api/mobile/setup/telegram", {"token": TOKEN}),
                               ("post", "/api/mobile/setup/page-booking", {"on": True})):
        r = getattr(client, method)(path, headers=staff, **({"json": body} if body else {}))
        assert r.status_code == 403 and r.json()["error"] == "Настройки компании меняет владелец."
    assert client.get("/api/mobile/setup").status_code == 401
    with db.new_session() as s:
        assert s.exec(select(Business).where(Business.id == business.id)).one().page_booking is False
