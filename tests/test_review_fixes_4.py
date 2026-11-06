"""Fifth independent review (PRs #111–#118): what it found, fixed and pinned down.

1–2. A master's login sees and changes only her own bookings, customers and cash — nothing else of the business.
3. A catalog item with stock history can be deleted.
4–6, 14. Stock: lines of one item count together, a clamp never invents stock, restoring a cancelled order takes it
   again, the owner's stop list survives a recount.
7. A payment is validated. 8. The CSV does not carry formulas. 9. The service worker is network-first.
10. The funnel looks at 30 days only. 11. A future booking is not a visit. 12. The booking page does not promise an
   AI that is off. 13. A bad recount is an error, not «stop tracking». 15. Yesterday's cash on a quiet morning.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import customers, db, funnel, stock
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, Lead, Order, OrderLine, PanelUser, Service, Staff, StockMove
from joop.security import hash_password
from joop.timeutil import utc_to_local
from joop.web.app import _login_fails, create_app

from .conftest import NOW_UTC, FakeLLM
from .test_niches import item, make, say
from .test_web import client, csrf_of, login  # noqa: F401  (fixture)

LOCAL = utc_to_local(NOW_UTC, "Asia/Bishkek")


def _two_masters(business_id):
    with db.new_session() as s:
        a, b2 = s.exec(select(Staff).where(Staff.business_id == business_id).order_by(Staff.id)).all()[:2]
        mine = Booking(business_id=business_id, staff_id=a.id, staff_name=a.name, customer_name="Клиент А", customer_phone="+996555000001",
                       service="Консультация", start=LOCAL - timedelta(hours=2), channel="telegram")
        theirs = Booking(business_id=business_id, staff_id=b2.id, staff_name=b2.name, customer_name="Клиент Б", customer_phone="+996555000002",
                         service="Консультация", start=LOCAL - timedelta(hours=2), channel="telegram")
        s.add_all([mine, theirs])
        s.add(PanelUser(business_id=business_id, name="Мастер", login="master", password_hash=hash_password("staff-pass-1"), staff_id=a.id))
        s.commit()
        return mine.id, theirs.id


def _master_client(app):
    c = TestClient(app)
    token = csrf_of(c.get("/login").text)
    assert c.post("/login", data={"slug": "aktish", "user": "master", "password": "staff-pass-1", "csrf": token},
                  follow_redirects=False).status_code == 303
    return c


def test_a_masters_login_is_confined_to_her_own_work(business, rt, settings):
    """Findings 1 and 2."""
    _login_fails.clear()
    mine, theirs = _two_masters(business.id)
    with _master_client(create_app(settings, rt, init=False)) as c:
        assert c.get("/panel", follow_redirects=False).headers["location"] == "/panel/bookings"
        for path in ("/panel/conversations", "/panel/leads", "/panel/funnel", "/panel/orders", "/panel/stock", "/panel/services", "/panel/staff"):
            assert c.get(path).status_code == 403, path
        page = c.get("/panel/bookings").text
        assert 'href="/panel/conversations"' not in page and 'href="/panel/customers"' in page  # her menu only
        assert "Клиент Б" not in c.get("/panel/customers.csv").text and "Клиент А" in c.get("/panel/customers.csv").text
        token = csrf_of(page)
        assert c.post(f"/panel/bookings/{theirs}/pay", data={"csrf": token, "amount": "5000", "method": "cash"}).status_code == 404
        assert c.post(f"/panel/bookings/{theirs}/cancel", data={"csrf": token}).status_code == 404
        assert c.post("/panel/customers/555000002", data={"csrf": token, "note": "x"}).status_code == 404
        assert c.post(f"/panel/bookings/{mine}/pay", data={"csrf": token, "amount": "1000", "method": "cash"}, follow_redirects=False).status_code == 303
    with db.new_session() as s:
        assert s.get(Booking, theirs).paid_som == 0 and s.get(Booking, theirs).status == "booked" and s.get(Booking, mine).paid_som == 1000


def test_payment_is_validated(business, rt, settings):
    """Finding 7."""
    mine, _ = _two_masters(business.id)
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get("/panel/cash").text)
        for data in ({"amount": "9" * 25, "method": "cash"}, {"amount": "100", "method": "bitcoin"}, {"amount": "-5", "method": "cash"}):
            assert c.post(f"/panel/bookings/{mine}/pay", data={"csrf": token, **data}).status_code == 400
        with db.new_session() as s:
            row = s.get(Booking, mine)
            row.status = "cancelled"
            s.add(row)
            s.commit()
        assert c.post(f"/panel/bookings/{mine}/pay", data={"csrf": token, "amount": "100", "method": "cash"}).status_code == 400


def _restaurant_with_stock(count):
    b = make("restaurant")
    plov = item(b, "Плов")
    with db.new_session() as s:
        stock.recount(s, s.get(Service, plov.id), count, 0, "Владелец", NOW_UTC)
        biz = s.get(Business, b.id)
        biz.min_order = 0
        s.add(biz)
        s.commit()
    return b, plov


def _order(b, lines, ext):
    llm = FakeLLM([AgentReply("Принято!", order={"lines": lines, "mode": "pickup", "address": "", "time": "", "name": "Айбек",
                                                "phone": "0555 123 456", "comment": ""})])
    return say(b, "плов", llm, ext)


def test_stock_counts_lines_together_and_never_invents_pieces(engine):
    """Findings 4 and 5."""
    b, plov = _restaurant_with_stock(3)
    out = _order(b, [{"item_id": plov.id, "quantity": 2, "note": ""}, {"item_id": plov.id, "quantity": 2, "note": "острый"}], "x1")
    assert out.order_id is None and "осталось 3 шт." in out.reply  # 2 + 2 > 3
    order_id = _order(b, [{"item_id": plov.id, "quantity": 1, "note": ""}, {"item_id": plov.id, "quantity": 2, "note": ""}], "x2").order_id
    with db.new_session() as s:
        assert s.get(Service, plov.id).stock == 0
        stock.return_for_order(s, order_id, "Владелец", NOW_UTC)
        stock.return_for_order(s, order_id, "Владелец", NOW_UTC)  # twice: once
        assert s.get(Service, plov.id).stock == 3
        stock.take_for_order(s, order_id, NOW_UTC, "Владелец")  # the order restored: its claim is back
        stock.take_for_order(s, order_id, NOW_UTC, "Владелец")
        assert s.get(Service, plov.id).stock == 0
        stock.return_for_order(s, order_id, "Владелец", NOW_UTC)
        s.commit()
        assert s.get(Service, plov.id).stock == 3


def test_owners_stop_list_survives_a_recount_and_a_sold_out_item_comes_back(engine):
    """Finding 6."""
    b, plov = _restaurant_with_stock(1)
    _order(b, [{"item_id": plov.id, "quantity": 1, "note": ""}], "y1")
    with db.new_session() as s:
        row = s.get(Service, plov.id)
        assert row.available is False and row.sold_out is True
        stock.recount(s, row, 5, 0, "Владелец", NOW_UTC)
        assert row.available is True and row.sold_out is False  # sold out → back in stock
        row.available = False  # the owner stops it on purpose
        stock.recount(s, row, 9, 0, "Владелец", NOW_UTC)
        assert row.available is False  # stays stopped


def test_an_item_with_stock_history_can_be_deleted_and_a_bad_recount_is_an_error(engine, settings, rt):
    """Findings 3 and 13."""
    b, plov = _restaurant_with_stock(4)
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": b.slug, "password": "x" * 8, "csrf": token})
        token = csrf_of(c.get("/panel/stock").text)
        page = c.post(f"/panel/stock/{plov.id}", data={"csrf": token, "counted": "-3", "minimum": ""}, follow_redirects=True).text
        assert "целое число" in page
        with db.new_session() as s:
            assert s.get(Service, plov.id).stock == 4  # not untracked
        r = c.post(f"/panel/services/{plov.id}/delete", data={"csrf": token}, follow_redirects=False)
        assert r.status_code == 303
        with db.new_session() as s:
            assert s.get(Service, plov.id) is None and s.exec(select(StockMove).where(StockMove.service_id == plov.id)).all() == []


def test_csv_cells_cannot_be_formulas_and_future_bookings_are_not_visits(business):
    """Findings 8 and 11."""
    with db.new_session() as s:
        s.add(Booking(business_id=business.id, customer_name="=HYPERLINK(\"http://x\")", customer_phone="+996555000077", service="Консультация",
                      start=LOCAL + timedelta(days=3), channel="telegram"))
        s.commit()
        b = s.get(Business, business.id)
        customers.save_note(s, b, "555000077", "+1 скидка", "@vip")
        s.commit()
        card = customers.cards(s, b)["555000077"]
        assert card.visits == 0 and card.last_visit is None and card.upcoming is not None
        text = customers.export_csv(customers.listing(s, b), b.timezone)
    assert "'=HYPERLINK" in text and "'+1 скидка" in text and "'@vip" in text and ";+996555000077;" in text


def test_service_worker_is_network_first_for_static_files(client):
    """Finding 9."""
    sw = client.get("/sw.js").text
    assert "joop-shell-v2" in sw and "fetch(req).then((res)" in sw and "res.ok" in sw and ".catch(() => caches.match(req))" in sw


def test_funnel_looks_at_thirty_days(business):
    """Finding 10."""
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="old")
        s.add(conv)
        s.flush()
        s.add(Lead(business_id=business.id, conversation_id=conv.id, kind="request", channel="telegram", created_at=NOW_UTC - timedelta(days=90)))
        s.add(Booking(business_id=business.id, conversation_id=conv.id, start=LOCAL - timedelta(days=80), channel="telegram",
                      created_at=NOW_UTC - timedelta(days=85)))
        s.commit()
        assert funnel.advance(s, s.get(Business, business.id), NOW_UTC) == 0  # an old lead is left alone


def test_booking_page_promises_nothing_when_the_ai_is_off_and_lists_whatsapp_first(business, rt, settings):
    """Finding 12."""
    from joop.web.menu import channel_links

    b = Business(slug="x", name="X", bot_enabled=True, phone="0555 000 111", wa_phone_number_id="pn", wa_access_token="t",
                 telegram_bot_token="1:x", telegram_bot_username="x_bot")
    assert [n for _, n in channel_links(b, "https://joop.test", "ru")] == ["WhatsApp", "Telegram", "Чат на сайте"]
    b.bot_enabled = False
    assert channel_links(b, "https://joop.test", "ru") == []
    with db.new_session() as s:
        row = s.get(Business, business.id)
        row.menu_enabled, row.bot_enabled = True, False
        s.add(row)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        assert "Отвечает ИИ-администратор" not in c.get("/m/aktish").text


def test_yesterdays_cash_reaches_a_quiet_morning(business):
    """Finding 15."""
    from joop.scheduler import digest_text

    with db.new_session() as s:
        s.add(Booking(business_id=business.id, customer_name="Вчера", customer_phone="+996555000004", service="Консультация",
                      start=LOCAL - timedelta(days=1), channel="whatsapp", paid_som=500, paid_method="card"))
        s.commit()
        text = digest_text(s, s.get(Business, business.id), NOW_UTC)
    assert text and "Касса за вчера: 500 сом" in text


def test_the_last_piece_cannot_be_taken_twice(engine):
    """Finding 14: the take is one conditional statement; a second order for the same last piece is flagged to staff."""
    b, plov = _restaurant_with_stock(1)
    first = _order(b, [{"item_id": plov.id, "quantity": 1, "note": ""}], "z1").order_id
    with db.new_session() as s:
        # a second order that passed its check before the first one took the piece
        o = Order(business_id=b.id, customer_name="Нурлан", customer_phone="+996555000009", channel="telegram")
        s.add(o)
        s.flush()
        s.add(OrderLine(order_id=o.id, item_id=plov.id, name="Плов", quantity=1, unit_price=0))
        s.flush()
        notes = stock.take_for_order(s, o.id, NOW_UTC)
        s.commit()
        assert first and any("просили 1 шт., а осталось 0" in n for n in notes)
        assert s.get(Service, plov.id).stock == 0


def test_sixth_review_master_sees_no_waitlist_no_other_masters_and_loses_access_with_her_staff_record(business, rt, settings):
    """Sixth review (PRs #111–#120), findings 3, 4 and the master login that outlived her staff record."""
    from joop.models import WaitlistEntry

    _login_fails.clear()
    mine, theirs = _two_masters(business.id)
    with db.new_session() as s:
        other = s.get(Booking, theirs)
        other.customer_phone = "+996555000001"  # the same customer also goes to another master
        other.paid_som, other.status = 9000, "booked"
        s.add(other)
        s.add(WaitlistEntry(business_id=business.id, customer_name="Ожидает Чужой", customer_phone="+996555999999", channel="telegram",
                            chat_id="1", service="Консультация"))
        s.commit()
        a_id = s.get(Booking, mine).staff_id
    app = create_app(settings, rt, init=False)
    with _master_client(app) as c:
        assert "Ожидает Чужой" not in c.get("/panel/bookings").text
        card = c.get("/panel/customers/555000001").text
        assert "9000" not in card and "9 000" not in card and other.staff_name not in card and "Диалоги" not in card
        assert "9000" not in c.get("/panel/customers.csv").text
    with TestClient(app) as owner:
        login(owner)
        assert "Ожидает Чужой" in owner.get("/panel/bookings").text
        token = csrf_of(owner.get("/panel/staff").text)
        owner.post(f"/panel/staff/{a_id}/delete", data={"csrf": token})
        assert "9 000" in owner.get("/panel/customers/555000001").text or "9000" in owner.get("/panel/customers/555000001").text
    with db.new_session() as s:
        assert s.exec(select(PanelUser).where(PanelUser.login == "master")).one().active is False


def test_sixth_review_unicode_digits_are_a_message_not_a_crash(client):  # noqa: F811
    login(client)
    with db.new_session() as s:
        item_id = s.exec(select(Service)).first().id
    token = csrf_of(client.get("/panel/stock").text)
    r = client.post(f"/panel/stock/{item_id}", data={"csrf": token, "counted": "²", "minimum": ""}, follow_redirects=True)
    assert r.status_code == 200 and "целое число" in r.text
