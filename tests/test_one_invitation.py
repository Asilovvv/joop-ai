"""One invitation to come again, then two weeks of quiet, whoever sent it (joop/followups.py, joop/gaps.py).

The automatic invitation and the one the owner sends from «Пустые окна» did not know about each other: a customer due
for a repeat visit could get both within days, and a visit with two services got two automatic ones in a row."""

from datetime import timedelta

from fastapi.testclient import TestClient

from joop import db, followups, gaps
from joop.models import Booking, Business, Conversation
from joop.scheduler import run_due_jobs
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .test_followups import DAY_UTC, enable, visit
from .test_gaps import _interval
from .test_web import login

CLEANING, CHECKUP = "Профессиональная чистка", "Консультация и осмотр"
LOCAL = utc_to_local(DAY_UTC, "Asia/Bishkek")
AGAIN = "Записать вас снова"


def invited(rt) -> list[str]:
    return [chat for chat, text in rt.tg.sent if AGAIN in text]


def jobs(business_id, rt, now=DAY_UTC) -> dict:
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business_id), now)
        s.commit()
        return report["returns"]


def offered(business_id, now_local=LOCAL + timedelta(hours=1)) -> list[int]:
    with db.new_session() as s:
        return [c.conversation_id for c in gaps.candidates(s, s.get(Business, business_id), now_local)]


def test_free_slots_do_not_offer_whom_the_automatic_invitation_just_reached(business, rt):
    _interval(business.id, CLEANING, 21)
    enable(business.id, return_invites=True, reminder_hour=15)
    booking, conv = visit(business.id, LOCAL - timedelta(days=21), chat="801", phone="0555 801 801")
    assert offered(business.id) == [conv]  # due: «пора»
    assert jobs(business.id, rt) == {"sent": 1, "manual": 0} and invited(rt) == ["801"]
    with db.new_session() as s:
        assert s.get(Booking, booking).return_sent_at == DAY_UTC
        assert gaps.week_numbers(s, s.get(Business, business.id), DAY_UTC - timedelta(days=7)) == (0, 0)  # not «Пустые окна»'s
    assert offered(business.id) == []  # invited an hour ago: the owner is not offered to write again
    assert offered(business.id, LOCAL + timedelta(days=13)) == []
    with db.new_session() as s:  # two weeks on, the customer has still not come: worth another word
        b = s.get(Booking, booking)
        b.return_sent_at = DAY_UTC - timedelta(days=followups.QUIET_DAYS, hours=1)
        s.add(b)
        s.commit()
    assert offered(business.id) == [conv]


def test_the_automatic_invitation_waits_after_one_from_free_slots(business, rt):
    _interval(business.id, CLEANING, 21)
    enable(business.id, return_invites=True, reminder_hour=15)
    by_hand, conv = visit(business.id, LOCAL - timedelta(days=21), chat="801", phone="0555 801 801")
    nobody, _ = visit(business.id, LOCAL - timedelta(days=21), chat="802", phone="0555 802 802")
    long_ago, old = visit(business.id, LOCAL - timedelta(days=21), chat="803", phone="0555 803 803")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        cand = next(c for c in gaps.candidates(s, b, LOCAL) if c.conversation_id == conv)
        assert gaps.send(s, rt, b, cand, DAY_UTC - timedelta(days=3))  # the owner, three days ago
        was = s.get(Conversation, old)
        was.invited_at = DAY_UTC - timedelta(days=followups.QUIET_DAYS + 1)  # and this one over two weeks ago
        s.add(was)
        s.commit()
    assert jobs(business.id, rt) == {"sent": 2, "manual": 0}
    assert sorted(invited(rt)) == ["802", "803"]  # «801» has the owner's invitation of three days ago
    with db.new_session() as s:
        assert [s.get(Booking, i).return_status for i in (by_hand, nobody, long_ago)] == ["", "sent", "sent"]
    # the days in which the automatic one may go run out before the two weeks do: «801» gets none
    for days in (1, 2, 3, 4, 12):
        assert jobs(business.id, rt, DAY_UTC + timedelta(days=days)) == {"sent": 0, "manual": 0}
    assert sorted(invited(rt)) == ["802", "803"]


def test_two_services_of_one_visit_are_one_invitation(business, rt):
    _interval(business.id, CLEANING, 21)
    _interval(business.id, CHECKUP, 21)
    enable(business.id, return_invites=True, reminder_hour=15)
    start = LOCAL - timedelta(days=21)
    _, conv = visit(business.id, start, chat="801", service=CLEANING, phone="0555 801 801")
    with db.new_session() as s:  # the same visit: another service at the same time, and one booked from another chat
        s.add(Booking(business_id=business.id, conversation_id=conv, start=start, service=CHECKUP, staff_name="Доктор",
                      customer_name="Айбек", customer_phone="0555 801 801", channel="telegram", chat_id="801"))
        s.commit()
    visit(business.id, start, chat="805", service=CHECKUP, phone="+996 555 801 801")
    assert jobs(business.id, rt) == {"sent": 1, "manual": 0}
    assert len(invited(rt)) == 1
    assert jobs(business.id, rt, DAY_UTC + timedelta(days=1)) == {"sent": 0, "manual": 0} and len(invited(rt)) == 1


def test_an_invitation_answered_with_a_visit_does_not_silence_the_next(business, rt):
    """A service every week: the invitation after one visit brought the customer back. The quiet is for a customer who
    has not come; here the next visit is its own occasion, eight days after the last invitation."""
    _interval(business.id, CLEANING, 7)
    enable(business.id, return_invites=True, reminder_hour=15)
    first, conv = visit(business.id, LOCAL - timedelta(days=15), chat="801", phone="0555 801 801")
    _, by_owner = visit(business.id, LOCAL - timedelta(days=15), chat="802", phone="0555 802 802")
    with db.new_session() as s:
        old = s.get(Booking, first)
        old.return_status, old.return_sent_at = "sent", DAY_UTC - timedelta(days=8)  # invited; they came the next day
        s.add(old)
        owner = s.get(Conversation, by_owner)
        owner.invited_at = DAY_UTC - timedelta(days=8)  # this one the owner invited from «Пустые окна»; they came too
        s.add(owner)
        for conv_id, chat, phone in ((conv, "801", "0555 801 801"), (by_owner, "802", "0555 802 802")):
            s.add(Booking(business_id=business.id, conversation_id=conv_id, start=LOCAL - timedelta(days=7), service=CLEANING,
                          staff_name="Доктор", customer_name="Айбек", customer_phone=phone, channel="telegram", chat_id=chat))
        s.commit()
    assert sorted(offered(business.id)) == sorted([conv, by_owner])  # due again: neither invitation hides them now
    assert jobs(business.id, rt) == {"sent": 2, "manual": 0}
    assert sorted(invited(rt)) == ["801", "802"]


def test_the_panel_says_so(business, rt, settings):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert "или их уже приглашали в последние две недели (вы отсюда или ИИ сам)" in c.get("/panel/gaps").text
        assert "или вы пригласили его из «Пустых окон» в последние две недели, приглашения не будет" in c.get("/panel/followups").text
