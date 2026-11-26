"""The public page switched on from the owner's app: a cafe's QR menu (and any business's price page) answered 404
after a sign-up on the phone until the owner found the switch in the panel (cafe walk, 26.11.2026)."""

from fastapi.testclient import TestClient

from joop.web import mobile as web_mobile
from joop.web.app import create_app
from joop.web.menu import qr_rows

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

FORM = {"name": "Кафе Сайрам", "niche": "restaurant", "phone": "0555 123 456", "password": "sairam-2026", "contact_name": "Нурлан"}


def test_a_cafe_turns_its_qr_menu_on_from_the_phone(engine, settings, rt):
    web_mobile._signups.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        r = c.post("/api/mobile/signup", json=FORM).json()
        h, slug = auth(r["token"]), r["business"]["slug"]
        online = c.get("/api/mobile/setup", headers=h).json()["online"]
        assert online == {"label": "QR-меню", "on": False, "tables": True, "url": f"https://joop.test/m/{slug}",
                          "qr": qr_rows(f"https://joop.test/m/{slug}")}
        assert c.get(f"/m/{slug}?t=5").status_code == 404
        r = c.post("/api/mobile/setup/online", headers=h, json={"on": True})
        assert r.status_code == 200 and r.json()["online"]["on"] is True
        page = c.get(f"/m/{slug}?t=5")
        assert page.status_code == 200 and "Кафе Сайрам" in page.text
        # off again: the page and booking by link, which lives on it, both stop
        c.post("/api/mobile/setup/page-booking", headers=h, json={"on": True})
        assert c.get(f"/m/{slug}/book").status_code == 200
        data = c.post("/api/mobile/setup/online", headers=h, json={"on": False}).json()
        assert data["online"]["on"] is False and data["page_booking"]["on"] is False and data["page_booking"]["why"] == "page"
        assert c.get(f"/m/{slug}?t=5").status_code == 404


def test_a_price_page_is_named_as_the_panel_names_it_and_only_the_owner_switches_it(client, business):
    h = auth(sign_in(client).json()["token"])
    assert client.get("/api/mobile/setup", headers=h).json()["online"]["label"] == "Прайс онлайн"
    from joop import db
    from joop.models import PanelUser
    from joop.security import hash_password

    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, login="admin1", name="Админ", password_hash=hash_password("staff-pass-1")))
        s.commit()
    ha = auth(sign_in(client, user="admin1", password="staff-pass-1").json()["token"])
    assert client.post("/api/mobile/setup/online", headers=ha, json={"on": True}).status_code == 403
    assert client.post("/api/mobile/setup/online", json={"on": True}).status_code == 401
