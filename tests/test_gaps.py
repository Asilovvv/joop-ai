"""Empty slots and who to invite into them (joop/gaps.py, /panel/gaps)."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, gaps
from joop.models import Booking, Business, Conversation, Message, Service
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of, login

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").replace(hour=12, minute=0, second=0, microsecond=0)


def _customer(business_id, chat, phone, name, visits, channel="telegram", last_customer_days_ago=40, opt_out=False):
    """A customer with a chat and past visits; `visits` = [(days_ago, service, staff)]."""
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel=channel, chat_id=chat, customer_name=name, customer_phone=phone,
                            last_customer_at=NOW_UTC - timedelta(days=last_customer_days_ago), broadcast_opt_out=opt_out)
        s.add(conv)
        s.flush()
        for days_ago, service, staff in visits:
            s.add(Booking(business_id=business_id, conversation_id=conv.id, customer_name=name, customer_phone=phone, service=service,
                          staff_name=staff, start=TODAY - timedelta(days=days_ago), channel=channel, source="ai",
                          created_at=NOW_UTC - timedelta(days=days_ago + 1)))
        s.commit()
        return conv.id


def _interval(business_id, name, days):
    with db.new_session() as s:
        row = s.exec(select(Service).where(Service.business_id == business_id, Service.name == name)).first()
        row.repeat_days = days
        s.add(row)
        s.commit()


def test_candidates_due_by_interval_or_long_absent_with_the_right_exclusions(business):
    _interval(business.id, "Профессиональная чистка", 180)
    due = _customer(business.id, "1001", "+996555000001", "Айбек", [(190, "Профессиональная чистка", "Айгерим Садыкова")])
    absent = _customer(business.id, "1002", "+996555000002", "Нурлан", [(70, "Консультация и осмотр", "Нурлан Абдыкадыров"),
                                                                         (120, "Консультация и осмотр", "Нурлан Абдыкадыров")])
    _customer(business.id, "1003", "+996555000003", "Асель", [(70, "Консультация и осмотр", "")])  # once only: not a regular
    _customer(business.id, "1004", "+996555000004", "Жылдыз", [(190, "Профессиональная чистка", ""), (-2, "Консультация и осмотр", "")])  # booked
    _customer(business.id, "1005", "+996555000005", "Бакыт", [(190, "Профессиональная чистка", "")], opt_out=True)
    _customer(business.id, "1006", "+996555000006", "Гүлнара", [(10, "Профессиональная чистка", "")])  # not due yet
    with db.new_session() as s:
        b = s.get(Business, business.id)
        rows = gaps.candidates(s, b, TODAY)
    by = {c.name: c for c in rows}
    assert list(by) == ["Айбек", "Нурлан"]
    assert by["Айбек"].reason == "пора: Профессиональная чистка раз в 180 дн., прошло 190" and by["Айбек"].conversation_id == due
    assert by["Нурлан"].reason == "давно не был(а): 70 дн., визитов 2" and by["Нурлан"].conversation_id == absent
    assert by["Айбек"].reachable and by["Айбек"].staff == "Айгерим Садыкова"
    assert by["Айбек"].text.startswith("Здравствуйте, Айбек! В «Ак-Тиш Дент» есть свободное время у Айгерим Садыкова: ")
    assert by["Айбек"].text.endswith("Записать вас на «Профессиональная чистка»? Напишите «да» или другое удобное время.")
    assert len(by["Айбек"].slots) == 2 and all(st == "Айгерим Садыкова" for _, st in by["Айбек"].slots)


def test_whatsapp_customer_outside_the_window_is_a_call_not_a_message(business):
    _customer(business.id, "996555000007", "+996555000007", "Эркин", [(70, "Консультация и осмотр", ""), (100, "Консультация и осмотр", "")],
              channel="whatsapp", last_customer_days_ago=70)
    _customer(business.id, "996555000008", "+996555000008", "Айпери", [(70, "Консультация и осмотр", ""), (100, "Консультация и осмотр", "")],
              channel="whatsapp", last_customer_days_ago=0)
    with db.new_session() as s:
        rows = {c.name: c for c in gaps.candidates(s, s.get(Business, business.id), TODAY)}
    assert not rows["Эркин"].reachable and rows["Айпери"].reachable


def test_page_send_one_and_send_all_mark_the_invitation(business, rt, settings):
    _interval(business.id, "Профессиональная чистка", 180)
    cid = _customer(business.id, "1001", "+996555000001", "Айбек", [(190, "Профессиональная чистка", "Айгерим Садыкова")])
    _customer(business.id, "1002", "+996555000002", "Нурлан", [(70, "Консультация и осмотр", ""), (120, "Консультация и осмотр", "")])
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/gaps").text
        assert "Пустые окна" in page and "Айбек" in page and "Нурлан" in page and "свободных окон" in page
        token = csrf_of(page)
        r = c.post(f"/panel/gaps/{cid}/send", data={"csrf": token})
        assert "Приглашение отправлено" in r.text
        assert any(chat == "1001" and t.startswith("Здравствуйте, Айбек!") for chat, t in rt.tg.sent)
        with db.new_session() as s:
            conv = s.get(Conversation, cid)
            assert conv.invited_at is not None
            assert s.exec(select(Message).where(Message.conversation_id == cid, Message.role == "ai")).first() is not None
            assert [x.name for x in gaps.candidates(s, s.get(Business, business.id), TODAY)] == ["Нурлан"]  # invited: out for 14 days
        r = c.post("/panel/gaps/send-all", data={"csrf": token})
        assert "Отправлено: 1" in r.text
        with db.new_session() as s:
            assert gaps.candidates(s, s.get(Business, business.id), TODAY) == []


def test_weekly_report_counts_invitations_and_returns(business, rt):
    from joop.scheduler import weekly_report_text

    _interval(business.id, "Профессиональная чистка", 180)
    cid = _customer(business.id, "1001", "+996555000001", "Айбек", [(190, "Профессиональная чистка", "Айгерим Садыкова")])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        [cand] = gaps.candidates(s, b, TODAY)
        assert gaps.send(s, rt, b, cand, NOW_UTC)
        s.add(Booking(business_id=b.id, conversation_id=cid, customer_name="Айбек", customer_phone="+996555000001", start=TODAY + timedelta(days=2),
                      channel="telegram", source="ai", created_at=NOW_UTC + timedelta(hours=1)))
        s.add(Message(business_id=b.id, conversation_id=cid, role="customer", text="?", created_at=NOW_UTC))
        s.commit()
        text = weekly_report_text(s, b, NOW_UTC + timedelta(days=1))
    assert "Пригласили в пустые окна: 1, записались: 1." in text
