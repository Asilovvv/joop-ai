"""Broadcasts to customer groups (joop/broadcasts.py, joop/web/broadcasts.py)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import broadcasts, db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Broadcast, BroadcastDelivery, Business, Conversation, Message
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of, login

DAY = NOW_UTC - timedelta(hours=8)  # 15:14 in Bishkek: inside the sending hours
NIGHT = NOW_UTC  # 23:14: outside them
CLEANING = "Профессиональная чистка"


def person(business_id, chat, channel="telegram", wrote=DAY - timedelta(days=5), visits=(), opt_out=False, says="Здравствуйте"):
    """A customer: a conversation, their last message and bookings given as (days from DAY, service, status)."""
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel=channel, chat_id=chat, last_customer_at=wrote,
                            broadcast_opt_out=opt_out)
        s.add(conv)
        s.flush()
        if wrote:
            s.add(Message(business_id=business_id, conversation_id=conv.id, role="customer", text=says, created_at=wrote))
        b = s.get(Business, business_id)
        today = utc_to_local(DAY, b.timezone)
        for days, service, status in visits:
            s.add(Booking(business_id=business_id, conversation_id=conv.id, start=today + timedelta(days=days),
                          service=service, status=status, channel=channel, chat_id=chat))
        s.commit()
        return conv.id


@pytest.fixture
def people(business):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.wa_phone_number_id, b.wa_access_token, b.admin_chat_ids = "555", "wa-test", "999"
        s.add(b)
        s.commit()
    bid = business.id
    return {
        "recent": person(bid, "c1", visits=[(-10, CLEANING, "booked")]),
        "lapsed": person(bid, "c2", visits=[(-90, "Консультация", "booked")], says="Саламатсызбы, баасы канча?"),
        "coming": person(bid, "c3", visits=[(-90, "Консультация", "booked"), (3, CLEANING, "booked")]),
        "wa_new": person(bid, "c4", channel="whatsapp", wrote=DAY - timedelta(hours=2)),
        "ig_old": person(bid, "c5", channel="instagram", wrote=DAY - timedelta(days=3)),
        "stopped": person(bid, "c6", opt_out=True),
        "web": person(bid, "web-abc", channel="web"),
        "silent": person(bid, "c7", wrote=None),
        "cancelled": person(bid, "c8", visits=[(-5, CLEANING, "cancelled")]),
    }


def counts(business_id, segment, arg=""):
    with db.new_session() as s:
        p = broadcasts.preview(s, s.get(Business, business_id), segment, arg, DAY)
        return p.telegram, p.window, p.outside, p.opted_out


def test_groups_and_what_each_channel_allows(business, people):
    # telegram: recent, lapsed, coming, cancelled; WhatsApp within 24 hours; Instagram after 3 days: out; one unsubscribed
    assert counts(business.id, "all") == (4, 1, 1, 1)
    assert counts(business.id, "visited") == (3, 0, 0, 0)
    assert counts(business.id, "lapsed", "60") == (1, 0, 0, 0)  # 90 days ago and nothing booked ahead
    assert counts(business.id, "lapsed", "5") == (2, 0, 0, 0)  # minimum is 7 days: "recent" (10 days) joins
    assert counts(business.id, "service", CLEANING) == (1, 0, 0, 0)  # the future and the cancelled ones do not count
    assert counts(business.id, "no_booking") == (0, 1, 1, 1)
    assert list(broadcasts.segments_for(False)) == ["all"]  # a shop without bookings has only "everybody"


def test_sending_in_batches_within_hours_with_footer_and_kyrgyz(business, people, rt, monkeypatch):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        item, error = broadcasts.start(s, b, "Скидка 20% на чистку на этой неделе!", "Ушул жумада тазалоого 20% арзандатуу!",
                                       "all", "", True, DAY)
        s.commit()
        assert error == "" and item.total == 5  # four in Telegram and one in WhatsApp
    with db.new_session() as s:
        assert broadcasts.send_due(s, rt, s.get(Business, business.id), NIGHT) == {}  # nobody is woken up at night
    assert rt.tg.sent == []
    monkeypatch.setattr(broadcasts, "BATCH", 3)
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), DAY)
        s.commit()
    assert report["broadcast"] == {"sent": 3, "finished": 0}
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), DAY + timedelta(minutes=5))
        s.commit()
        item = s.exec(select(Broadcast)).one()
        assert report["broadcast"] == {"sent": 2, "finished": 1}
        assert (item.status, item.sent, item.skipped) == ("done", 5, 0)
    to = {chat: text for chat, text in rt.tg.sent + rt.wa.sent}
    assert to["c1"] == "Скидка 20% на чистку на этой неделе!\n\n" + broadcasts.FOOTER
    assert to["c2"] == "Ушул жумада тазалоого 20% арзандатуу!\n\n" + broadcasts.FOOTER_KY  # writes in Kyrgyz
    assert "c4" in to and not {"c5", "c6", "web-abc", "c7"} & set(to)
    assert "получили 5 из 5" in to["999"]  # the owner's summary
    with db.new_session() as s:  # the message stays in the dialogue, so the AI sees what the customer answers
        assert s.exec(select(Message).where(Message.conversation_id == people["recent"], Message.role == "ai")).one().text.startswith("Скидка")


def test_one_a_day_and_checks(business, people):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert broadcasts.start(s, b, " ", "", "all", "", True, DAY)[1] == "Напишите текст рассылки."
        assert "длиннее" in broadcasts.start(s, b, "х" * 1001, "", "all", "", True, DAY)[1]
        assert broadcasts.start(s, b, "Текст", "", "visited", "", False, DAY)[1] == "Выберите группу клиентов."
        assert broadcasts.start(s, b, "Текст", "", "service", "Нет такой", True, DAY)[1] == "В этой группе сейчас некому отправить."
        first, _ = broadcasts.start(s, b, "Первая", "", "all", "", True, DAY)
        broadcasts.cancel(s, first, DAY)  # stopped before anything went out: does not count
        assert first.status == "cancelled" and first.skipped == 5
        second, _ = broadcasts.start(s, b, "Вторая", "", "all", "", True, DAY)
        assert second is not None
        _, error = broadcasts.start(s, b, "Третья", "", "all", "", True, DAY + timedelta(hours=5))
        assert "не чаще раза в сутки" in error and "05.11 15:14" in error
        assert broadcasts.start(s, b, "Третья", "", "all", "", True, DAY + timedelta(hours=25))[0] is not None


def say(business_id, rt, chat, text, channel="telegram", now=DAY):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text), rt.get_llm, now)
        s.commit()
        return out


def opted_out(conv_id):
    with db.new_session() as s:
        return s.get(Conversation, conv_id).broadcast_opt_out


def test_stop_after_a_broadcast_and_subscribe_again(business, people, rt):
    rt._llm = FakeLLM([AgentReply("Хорошо, подожду.")])
    assert say(business.id, rt, "c1", "Стоп").reply == "Хорошо, подожду."  # no broadcast yet: "стоп" means "wait"
    assert opted_out(people["recent"]) is False
    with db.new_session() as s:
        b = s.get(Business, business.id)
        broadcasts.start(s, b, "Акция", "", "all", "", True, DAY)
        s.commit()
    with db.new_session() as s:
        broadcasts.send_due(s, rt, s.get(Business, business.id), DAY)
        s.commit()
    assert say(business.id, rt, "c1", "Стоп!").reply == broadcasts.OPT_OUT_REPLY
    assert opted_out(people["recent"]) is True
    assert say(business.id, rt, "c2", "токтот").reply == broadcasts.OPT_OUT_REPLY_KY
    assert say(business.id, rt, "c1", "Подписаться").reply == broadcasts.OPT_IN_REPLY
    assert opted_out(people["recent"]) is False
    assert say(business.id, rt, "c5", "Отписаться", channel="instagram").reply == broadcasts.OPT_OUT_REPLY  # always works
    assert len(rt._llm.calls) == 1  # none of these went to the model
    with db.new_session() as s:  # while staff answer by hand the bot is silent, but the wish is kept
        conv = s.get(Conversation, people["coming"])
        conv.ai_paused_until = DAY + timedelta(hours=1)
        s.add(conv)
        s.commit()
    assert say(business.id, rt, "c3", "стоп").skipped == "paused" and opted_out(people["coming"]) is True


def test_the_unsubscribed_customer_is_skipped_mid_broadcast(business, people, rt):
    with db.new_session() as s:
        broadcasts.start(s, s.get(Business, business.id), "Акция", "", "visited", "", True, DAY)
        conv = s.get(Conversation, people["lapsed"])
        conv.broadcast_opt_out = True  # said "отписаться" after the list was made
        s.add(conv)
        s.commit()
    with db.new_session() as s:
        broadcasts.send_due(s, rt, s.get(Business, business.id), DAY)
        s.commit()
        item = s.exec(select(Broadcast)).one()
        assert (item.sent, item.skipped, item.status) == (2, 1, "done")
        assert "Не дошло 1" in broadcasts.finished_note(item)
        assert s.exec(select(BroadcastDelivery).where(BroadcastDelivery.conversation_id == people["lapsed"])).one().status == "skipped"


@pytest.fixture
def web(settings, rt, business, people, monkeypatch):
    import joop.web.broadcasts as page

    monkeypatch.setattr(page, "utcnow", lambda: DAY)
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def test_panel_preview_test_send_and_stop(web, business, rt):
    token = login(web)
    page = web.get("/panel/broadcasts").text
    assert 'href="/panel/broadcasts"' in page and "Новая рассылка" in page and "Рассылок пока не было" in page
    form = {"csrf": token, "segment": "all", "text": "Свободные окна в субботу", "text_ky": ""}
    page = web.post("/panel/broadcasts", data={**form, "action": "preview"}).text
    assert "Отправить 5 клиентам" in page and "Telegram 4, WhatsApp и Instagram 1" in page
    page = web.post("/panel/broadcasts", data={**form, "action": "test"}).text
    assert "Пробное сообщение отправлено" in page
    assert ("999", "Свободные окна в субботу\n\n" + broadcasts.FOOTER) in rt.tg.sent
    r = web.post("/panel/broadcasts", data={**form, "action": "send"}, follow_redirects=False)
    assert r.status_code == 303
    page = web.get("/panel/broadcasts").text
    assert "Рассылка запущена: 5 клиентам" in page and "отправляется: 0 из 5" in page
    page = web.post("/panel/broadcasts", data={**form, "action": "send"}).text
    assert "не чаще раза в сутки" in page
    with db.new_session() as s:
        item = s.exec(select(Broadcast)).one()
    r = web.post(f"/panel/broadcasts/{item.id}/stop", data={"csrf": csrf_of(page)}, follow_redirects=False)
    assert r.status_code == 303 and "остановлена: получили 0 из 5" in web.get("/panel/broadcasts").text
    assert web.post("/panel/broadcasts/9999/stop", data={"csrf": token}).status_code == 404
