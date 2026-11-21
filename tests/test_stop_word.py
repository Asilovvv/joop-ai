"""A bare «стоп» as an answer to what the business sent first (joop/broadcasts.py: opt_change).

Review of #270: a rating request answered with «стоп» left the customer subscribed, and so did «стоп» after
«напишем, когда появится», whose own text asks for that word.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import broadcasts, db, followups, gaps
from joop.agent.llm import AgentReply
from joop.models import Booking, Business, Conversation, Service, StockWatch
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_followups import DAY_UTC, enable, say, visit
from .test_gaps import TODAY, _customer, _interval
from .test_holds import with_bot
from .test_pharmacy import pharmacy
from .test_restock import ask, restock_masks
from .test_restock import run as tell_back
from .test_unfinished import ASKED_UTC, LATER, _run, _say, _turn_on

WAIT = "Хорошо, подожду."


def model():
    return FakeLLM([AgentReply(WAIT)])


def jobs(business_id, rt, now):
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business_id), now)
        s.commit()
        return report


def silenced(conv_id):
    with db.new_session() as s:
        return s.get(Conversation, conv_id).silenced


def test_stop_answers_a_rating_request(business, rt):
    enable(business.id, review_requests=True)
    local = utc_to_local(DAY_UTC, business.timezone)
    _, conv_id = visit(business.id, local - timedelta(hours=3), chat="701")
    jobs(business.id, rt, DAY_UTC)
    assert rt.tg.sent[-1][0] == "701" and "Оцените" in rt.tg.sent[-1][1]
    llm = model()
    assert say(business.id, "701", "Стоп", llm, "s1", DAY_UTC + timedelta(minutes=5)).reply == broadcasts.OPT_OUT_REPLY
    assert silenced(conv_id) and llm.calls == []  # their word, not the model's guess
    after, _ = visit(business.id, local + timedelta(days=30) - timedelta(hours=3), chat="701-next")  # another chat: still asked
    with db.new_session() as s:
        again = Booking(business_id=business.id, conversation_id=conv_id, start=local + timedelta(days=30) - timedelta(hours=3),
                        service="Профессиональная чистка", staff_name="Доктор", customer_name="Айбек", channel="telegram", chat_id="701")
        s.add(again)
        s.commit()
        again_id = again.id
    sent = len(rt.tg.sent)
    jobs(business.id, rt, DAY_UTC + timedelta(days=30))
    assert [chat for chat, _ in rt.tg.sent[sent:]] == ["701-next"]
    with db.new_session() as s:
        assert s.get(Booking, again_id).review_status == "skipped" and s.get(Booking, after).review_status == "asked"


def test_stop_later_in_the_talk_still_means_wait(business, rt):
    """They got a request, then asked about something else: now «стоп» is about the talk, as before."""
    enable(business.id, review_requests=True)
    local = utc_to_local(DAY_UTC, business.timezone)
    _, conv_id = visit(business.id, local - timedelta(hours=3), chat="702")
    jobs(business.id, rt, DAY_UTC)
    llm = FakeLLM([AgentReply("Чистка — 3 000 сом."), AgentReply(WAIT)])
    say(business.id, "702", "А чистка сколько стоит?", llm, "q1", DAY_UTC + timedelta(minutes=5))
    assert say(business.id, "702", "стоп", llm, "q2", DAY_UTC + timedelta(minutes=6)).reply == WAIT
    assert not silenced(conv_id)


def test_stop_answers_an_invitation_to_come_again(business, rt):
    with db.new_session() as s:
        svc = s.exec(select(Service).where(Service.business_id == business.id)).first()
        svc.repeat_days = 21
        s.add(svc)
        s.commit()
        name = svc.name
    enable(business.id, return_invites=True, reminder_hour=15)
    local = utc_to_local(DAY_UTC, business.timezone)
    _, stops = visit(business.id, local - timedelta(days=21), chat="801", service=name, phone="0555 801 801")
    _, declines = visit(business.id, local - timedelta(days=21), chat="802", service=name, phone="0555 802 802")
    assert jobs(business.id, rt, DAY_UTC)["returns"] == {"sent": 2, "manual": 0}
    llm = model()
    assert say(business.id, "801", "не пишите", llm, "r1", DAY_UTC + timedelta(hours=1)).reply == broadcasts.OPT_OUT_REPLY
    assert silenced(stops) and llm.calls == []
    # «керек эмес» to «Записать вас снова?» is «не надо», not «никогда не пишите»: the model answers it
    assert say(business.id, "802", "керек эмес", llm, "r2", DAY_UTC + timedelta(hours=1)).reply == WAIT
    assert not silenced(declines)


def test_stop_answers_an_invitation_into_a_free_slot(business, rt):
    _interval(business.id, "Профессиональная чистка", 180)
    conv_id = _customer(business.id, "1001", "+996555000001", "Айбек", [(190, "Профессиональная чистка", "Айгерим Садыкова")])
    with db.new_session() as s:
        b = s.get(Business, business.id)
        cand = gaps.candidates(s, b, TODAY)[0]
        assert gaps.send(s, rt, b, cand, NOW_UTC)
        s.commit()
    llm = model()
    assert say(business.id, "1001", "хватит", llm, "g1", NOW_UTC + timedelta(minutes=3)).reply == broadcasts.OPT_OUT_REPLY
    assert silenced(conv_id) and llm.calls == []


def test_stop_answers_the_follow_up(business, rt):
    _turn_on(business.id)
    _say(business.id, rt, "Сколько стоит чистка?", llm=FakeLLM([AgentReply("Чистка — 3 000 сом.")]))
    assert _run(business, rt, LATER)["unfinished"] == {"sent": 1}
    llm = model()
    assert _say(business.id, rt, "токтот", now=LATER + timedelta(minutes=10), llm=llm).reply == broadcasts.OPT_OUT_REPLY_KY
    assert llm.calls == []
    with db.new_session() as s:
        assert s.exec(select(Conversation)).one().silenced


def test_stop_before_we_wrote_first_is_about_the_talk(business, rt):
    _turn_on(business.id)
    _say(business.id, rt, "Сколько стоит чистка?", llm=FakeLLM([AgentReply("Чистка — 3 000 сом.")]))
    llm = model()
    assert _say(business.id, rt, "стоп", now=ASKED_UTC + timedelta(minutes=1), llm=llm).reply == WAIT


def test_stop_answers_the_promise_to_write_when_it_is_back(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    assert ask(b.id, "Медицинские маски есть?", "a").reply.endswith("Не нужно — напишите «стоп».")
    assert ask(b.id, "Стоп", "b").reply == broadcasts.OPT_OUT_REPLY  # the reply itself asked for this word
    ask(b.id, "Маски нужны", "c", chat="c2")
    restock_masks(b.id)
    assert tell_back(rt, b.id, NOW_UTC + timedelta(days=2, hours=16)) == {"sent": 1}
    assert [chat for chat, text in rt.tg.sent if "снова в наличии" in text] == ["c2"]
    with db.new_session() as s:
        assert all(w.notified_at is not None for w in s.exec(select(StockWatch)).all())


def test_stop_answers_back_in_stock(engine, rt):
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage

    b = pharmacy()
    with_bot(b.id)
    ask(b.id, "Маски нужны", "a")
    restock_masks(b.id)
    told = NOW_UTC + timedelta(days=2, hours=16)
    assert tell_back(rt, b.id, told) == {"sent": 1}
    llm = model()
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "c1", "text", "stop", "", "z"), lambda: llm,
                              told + timedelta(minutes=2))
        s.commit()
        assert out.reply == broadcasts.OPT_OUT_REPLY and llm.calls == []
        assert s.exec(select(Conversation).where(Conversation.business_id == b.id)).one().silenced


def test_a_reminder_of_their_own_booking_is_not_something_to_unsubscribe_from(business, rt):
    """What the customer needs — a reminder, a moved time, an order's status — is not «такие сообщения»."""
    local = utc_to_local(DAY_UTC, business.timezone)
    _, conv_id = visit(business.id, local + timedelta(days=1), chat="901")
    with db.new_session() as s:
        assert followups.deliver_to_chat(s, rt, s.get(Business, business.id), s.get(Conversation, conv_id),
                                         "Напоминаем: завтра вас ждёт доктор.", DAY_UTC)
        s.commit()
    llm = model()
    assert say(business.id, "901", "стоп", llm, "n1", DAY_UTC + timedelta(minutes=5)).reply == WAIT
    assert not silenced(conv_id)


def test_the_privacy_page_promises_what_the_code_does(settings, rt, engine):
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/privacy").text
    assert "«стоп» в ответ на любое из них делает то же самое" in page
    assert "Напоминания о собственной записи и ответы на вопросы остаются" in page
