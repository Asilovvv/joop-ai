"""Ready answers in a dialogue (joop/quick_replies.py, /panel/replies)."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, quick_replies
from joop.models import Business, Conversation, Message, QuickReply
from joop.web.app import create_app

from .test_web import csrf_of, login


def _conv(business_id, name="Айгуль"):
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel="telegram", chat_id="77", customer_name=name)
        s.add(conv)
        s.commit()
        return conv.id


def test_fill_puts_in_the_name_and_drops_empty_fields(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.address = "Чуй 120"
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="1", customer_name="Айгуль")
        assert quick_replies.fill("{имя}, мы по адресу: {адрес}.", b, conv) == "Айгуль, мы по адресу: Чуй 120."
        assert quick_replies.fill("{имя}, спасибо! Ждём — {компания}.", b) == f"Спасибо! Ждём — {b.name}."
        b.phone = ""
        assert quick_replies.fill("Звоните: {телефон}", b) == "Звоните:"


def test_page_starters_and_limits(business, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/replies").text
        assert "Готовые ответы" in page and "Добавить примеры" in page and 'href="/panel/replies"' in page
        token = csrf_of(page)
        c.post("/panel/replies", data={"csrf": token, "action": "starters"})
        c.post("/panel/replies", data={"csrf": token, "action": "starters"})  # twice: no duplicates
        with db.new_session() as s:
            assert len(s.exec(select(QuickReply)).all()) == len(quick_replies.STARTERS)
        assert "Нужны название" in c.post("/panel/replies", data={"csrf": token, "title": " ", "text": "x"}, follow_redirects=True).text
        c.post("/panel/replies", data={"csrf": token, "title": "Цены", "text": "{имя}, прайс: <b>от 500</b>"})
        page = c.get("/panel/replies").text
        assert "&lt;b&gt;от 500" in page and "<b>от 500" not in page  # escaped
        with db.new_session() as s:
            row = s.exec(select(QuickReply).where(QuickReply.title == "Цены")).one()
        c.post(f"/panel/replies/{row.id}", data={"csrf": token, "title": "Цены", "text": "Прайс на сайте"})
        c.post(f"/panel/replies/{row.id}", data={"csrf": token, "action": "delete"})
        with db.new_session() as s:
            assert s.get(QuickReply, row.id) is None
        assert c.post("/panel/replies/9999", data={"csrf": token, "action": "delete"}).status_code == 404


def test_dialogue_shows_replies_and_prefills_without_sending(business, settings, rt):
    conv_id = _conv(business.id)
    with db.new_session() as s:
        s.add(QuickReply(business_id=business.id, title="Перезвоним", text="{имя}, перезвоним через 15 минут."))
        s.commit()
        rid = s.exec(select(QuickReply)).one().id
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get(f"/panel/conversations/{conv_id}").text
        assert f"?t={rid}#reply" in page and "Перезвоним" in page
        page = c.get(f"/panel/conversations/{conv_id}?t={rid}").text
        assert ">Айгуль, перезвоним через 15 минут.</textarea>" in page
        assert c.get(f"/panel/conversations/{conv_id}?t=424242").status_code == 200  # unknown id: empty box
    with db.new_session() as s:
        assert s.exec(select(Message).where(Message.conversation_id == conv_id)).all() == []  # nothing went out


def test_other_business_replies_are_not_reachable(business, settings, rt):
    with db.new_session() as s:
        other = Business(slug="other", name="Другой", password_hash="x")
        s.add(other)
        s.commit()
        s.add(QuickReply(business_id=other.id, title="Чужой", text="секрет"))
        s.commit()
        rid = s.exec(select(QuickReply)).one().id
    conv_id = _conv(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert "секрет" not in c.get(f"/panel/conversations/{conv_id}?t={rid}").text
        token = csrf_of(c.get("/panel/replies").text)
        assert c.post(f"/panel/replies/{rid}", data={"csrf": token, "title": "x", "text": "y"}).status_code == 404
