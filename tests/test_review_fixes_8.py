"""Eighth independent review (PRs #140-#145): the sign-up example, the free plan, hotels and the level test."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import billing, db, free_plan, placement, samples
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, PlacementAttempt, PlacementTest, Slot, Staff
from joop.presets import create_business
from joop.timeutil import utc_to_local
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_review_fixes_4 import _master_client, _two_masters
from .test_web import csrf_of

TODAY = utc_to_local(NOW_UTC, "Asia/Bishkek").date()


def _new(slug, niche):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Новый бизнес", password="long-password", niche=niche, demo=True, now_utc=NOW_UTC)
        s.commit()
        return b.id


def test_a_new_hotel_does_not_offer_or_book_its_example_rooms(engine):
    """Finding 1: the prompt listed the example rooms and a real guest could book them."""
    bid = _new("newhotel", "hotel")
    with db.new_session() as s:
        cottage = s.exec(select(Staff).where(Staff.business_id == bid, Staff.name == "Коттедж")).one().id
    d = TODAY + timedelta(days=10)
    data = {"room_id": cottage, "check_in": d.isoformat(), "check_out": (d + timedelta(days=2)).isoformat(), "guests": 2,
            "name": "Алмаз", "phone": "0555667788"}
    outs = {}
    for channel in ("telegram", "console"):
        llm = FakeLLM([AgentReply("Забронировала.", stay=data)])
        with db.new_session() as s:
            outs[channel] = handle_incoming(s, s.get(Business, bid), IncomingMessage(channel, f"c-{channel}", "text",
                                            "Коттедж, Алмаз 0555 667 788", "", f"e-{channel}"), lambda: llm, NOW_UTC)
            s.commit()
        if channel == "telegram":
            assert "Коттедж" not in llm.calls[0]["system"] and "номеров в данных нет" in llm.calls[0]["system"]
    assert outs["telegram"].stay_id is None and outs["console"].stay_id is not None  # the test chat keeps the example


def test_switching_the_niche_keeps_the_example_an_example(engine):
    """Finding 2: the example was recognised by the current niche, so a switch made it real data."""
    bid = _new("switcher", "beauty")
    with db.new_session() as s:
        b = s.get(Business, bid)
        billing.start_trial(s, b, 14, NOW_UTC)
        free_plan.switch(billing.get_subscription(s, bid))
        before = samples.left(s, b)
        b.niche = "spa"
        s.add(b)
        s.commit()
        after = samples.left(s, s.get(Business, bid))
        assert before.services and after.services == before.services and after.staff == before.staff
        assert free_plan.eligible(s, bid) and billing.access_ok(s, bid, NOW_UTC)


def test_the_demo_test_with_the_schools_own_questions_is_the_schools(engine):
    """Finding 3: a school that uploaded its own questions without renaming the test was cut off."""
    bid = _new("school2", "education")
    with db.new_session() as s:
        b = s.get(Business, bid)
        test = s.exec(select(PlacementTest).where(PlacementTest.business_id == bid)).one()
        assert samples.left(s, b).tests
        placement.replace_questions(s, test, [{"section": "", "text": f"Own question {i}", "options": ["a", "b"], "correct": 0}
                                              for i in range(10)])
        s.commit()
        assert samples.left(s, b).tests == []
        assert samples.warning(samples.left(s, b)).startswith("Ещё из примера")  # still other example rows


def test_a_demo_result_is_not_a_level_for_real_customers(engine):
    """Finding 4: a finished demo attempt still reached the prompt as the customer's level."""
    bid = _new("school3", "education")
    with db.new_session() as s:
        b = s.get(Business, bid)
        demo = s.exec(select(PlacementTest).where(PlacementTest.business_id == bid)).one()
        own = PlacementTest(business_id=bid, code=placement.new_code(), title="Наш тест", scale_text="0-1 A1\n2-2 A2")
        s.add(own)
        s.flush()
        placement.replace_questions(s, own, [{"section": "", "text": "Q", "options": ["a", "b"], "correct": 0}])
        conv = Conversation(business_id=bid, channel="telegram", chat_id="r1")
        s.add(conv)
        s.flush()
        s.add(PlacementAttempt(business_id=bid, test_id=demo.id, token="tok-demo-1", conversation_id=conv.id, status="finished",
                               score=7, max_score=8, level="B2", finished_at=NOW_UTC))
        s.commit()
        hint = placement.prompt_hint(s, b, conv, "https://joop.test")
        assert "Наш тест" in hint and "уже прошёл" not in hint and "B2" not in hint


def test_a_business_over_the_free_limit_can_still_edit_its_people(business, rt, settings):
    """Finding 5: with two real masters already (an Altegio sync), every staff edit was refused."""
    from .test_web import login

    with db.new_session() as s:
        billing.start_trial(s, s.get(Business, business.id), 14, NOW_UTC)
        free_plan.switch(billing.get_subscription(s, business.id))
        s.commit()
        first = s.exec(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id)).first()
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        r = c.post(f"/panel/staff/{first.id}", data={"csrf": token, "name": first.name, "role": first.role, "capacity": "3"})
        assert "На бесплатном тарифе один мастер" not in r.text
    with db.new_session() as s:
        assert s.get(Staff, first.id).capacity == 3


def test_example_warning_names_the_level_test():
    """Finding 6: only the demo test left gave «Ещё из примера — .»."""
    assert samples.warning(samples.Left(tests=["Английский: тест на уровень (демо)"])).startswith(
        "Ещё из примера — тест на уровень: Английский")


def test_example_times_do_not_crowd_out_a_real_masters_times(settings, rt, engine):
    """Finding 7: 60 example slots came first, so the real master's times never showed on /m."""
    bid = _new("crowded", "beauty")
    with db.new_session() as s:
        b = s.get(Business, bid)
        b.menu_enabled = True
        own = Staff(business_id=bid, name="Алина", role="мастер маникюра")
        s.add_all([b, own])
        s.flush()
        local = utc_to_local(NOW_UTC, b.timezone)
        s.add(Slot(business_id=bid, staff_id=own.id, start=(local + timedelta(days=5)).replace(hour=12, minute=0, second=0, microsecond=0)))
        s.commit()
        example_free = len(s.exec(select(Slot).where(Slot.business_id == bid, Slot.staff_id != own.id, Slot.status == "free")).all())
    assert example_free > 60
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/crowded").text
        assert "Алина" in page and "Ближайшее свободное время" in page


def test_a_master_cannot_mark_a_chat_as_a_customer(business, rt, settings):
    _two_masters(business.id)
    with db.new_session() as s:
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="t9", staff_test=True)
        s.add(conv)
        s.commit()
        cid = conv.id
    with _master_client(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/panel/bookings").text)
        assert c.post(f"/panel/conversations/{cid}/real", data={"csrf": token}).status_code == 403
    with db.new_session() as s:
        assert s.get(Conversation, cid).staff_test
