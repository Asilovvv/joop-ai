"""Instagram and Telegram shops (joop/niches/shop): every size is its own item with stock; the code counts the shelf."""

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Service
from joop.niches import get_pack
from joop.presets import create_business

from .conftest import NOW_UTC, FakeLLM


def shop():
    with db.new_session() as s:
        b = create_business(s, slug="shop", name="Бутик", password="shop-pass-123", niche="shop", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # this shop's catalog is its own (it equals the shop example)
        s.commit()
        items = {r.name: r for r in s.exec(select(Service).where(Service.business_id == b.id)).all()}
        return b, items


def order(item_id, qty=1, mode="delivery", address="Бишкек, Джал 23, кв. 5"):
    return AgentReply("Оформила заказ, менеджер подтвердит.", order={
        "lines": [{"item_id": item_id, "quantity": qty, "note": ""}], "mode": mode, "address": address, "time": "",
        "name": "Асель", "phone": "0555112233", "comment": ""})


def say(business_id, text, llm, ext, chat="s1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def test_pack_takes_orders_with_delivery_first():
    pack = get_pack("shop")
    assert pack.has("order") and not pack.has("booking") and pack.order_modes == ("delivery", "pickup")


def test_demo_stock_sold_out_size_is_not_offered_and_the_shelf_is_counted(engine):
    b, items = shop()
    sold_out, m = items["Платье миди бежевое, размер L"], items["Платье миди бежевое, размер M"]
    assert (sold_out.stock, sold_out.available, sold_out.sold_out) == (0, False, True)
    assert (m.stock, m.available) == (2, True) and items["Шопер льняной"].stock == 15
    llm = FakeLLM([order(m.id, qty=3), order(sold_out.id), order(m.id)])
    too_many = say(b.id, "3 платья M", llm, "o1")
    assert too_many.order_id is None and "«Платье миди бежевое, размер M» осталось 2 шт." in too_many.reply
    system = llm.calls[0]["system"]
    assert "Сейчас нет в наличии (не предлагай): Платье миди бежевое, размер L" in system
    assert f"[{m.id}] Платье миди бежевое, размер M" in system and "сетка: S — 42–44, M — 44–46, L — 46–48" in system
    assert "«Платье миди бежевое, размер L» сейчас нет в наличии" in say(b.id, "платье L", llm, "o2").reply
    ok = say(b.id, "одно платье M, Асель 0555 112 233, Джал 23", llm, "o3")
    assert ok.order_id and ok.reply.endswith("Сумма заказа: 3 400 сом.")  # no delivery fee set: goods only
    with db.new_session() as s:
        assert s.get(Service, m.id).stock == 1


def test_profiles_without_stock_stay_untracked(engine):
    with db.new_session() as s:
        b = create_business(s, slug="cafe", name="Кафе", password="cafe-pass-1", niche="restaurant", demo=True, now_utc=NOW_UTC)
        s.commit()
        rows = s.exec(select(Service).where(Service.business_id == b.id)).all()
    assert rows and all(r.stock is None and not r.sold_out for r in rows)


def test_price_page_speaks_of_a_shop_not_of_tables(settings, rt, engine):
    from fastapi.testclient import TestClient

    from joop.web.app import create_app

    from .test_web import csrf_of

    shop()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "shop", "password": "shop-pass-123", "csrf": token})
        token = csrf_of(c.get("/panel/menu").text)
        c.post("/panel/menu", data={"enabled": "1", "chat_url": "https://t.me/shop_bot", "csrf": token})
        page = c.get("/panel/menu").text
        assert "<h1>Каталог онлайн</h1>" in page and "в шапку Instagram" in page
        assert "стол" not in page.lower() and 'name="tables" value="0"' in page
        assert "Замените пример своими данными в разделе «Каталог»." not in page  # example_ok: nothing hidden
        public = c.get("/m/shop").text
        assert "Футболка белая оверсайз, размер M" in public and "1 200 сом" in public
    assert get_pack("restaurant").online_label == "QR-меню" and get_pack("dental").online_label == "Прайс онлайн"


def test_test_chat_and_launch_hints_follow_the_niche(settings, rt, engine):
    from fastapi.testclient import TestClient

    from joop.web.app import create_app
    from joop.web.saas import checklist

    from .test_web import csrf_of

    b, _ = shop()
    assert get_pack("shop").examples() == ("Сколько стоит бежевое платье миди?", "Кара худи канча турат?")
    assert get_pack("other").examples() == ("Сколько стоит консультация?", "Эртең жазылсам болобу?")  # no dialogues of its own
    with db.new_session() as s:
        hint = next(i["hint"] for i in checklist(s, s.get(Business, b.id), NOW_UTC) if i["key"] == "try")
    assert hint.endswith("спросите цену, закажите.")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "shop", "password": "shop-pass-123", "csrf": token})
        assert "Напишите, например: «Сколько стоит бежевое платье миди?» или «Кара худи канча турат?»" in c.get("/panel/try").text


def test_example_warning_names_only_the_sections_that_hold_the_example(settings, rt, engine):
    from fastapi.testclient import TestClient

    from joop.web.app import create_app

    from .test_web import csrf_of

    with db.new_session() as s:
        create_business(s, slug="shop2", name="Бутик 2", password="shop-pass-123", niche="shop", demo=True, now_utc=NOW_UTC)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "shop2", "password": "shop-pass-123", "csrf": token})
        page = c.get("/panel/menu").text
        assert "вымышленные цены. Замените пример своими данными в разделе «Каталог»." in page and "Менеджеры" not in page
