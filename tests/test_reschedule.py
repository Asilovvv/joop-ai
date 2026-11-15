"""Moving a booking to another free time (joop/reschedule.py) from the panel's «Перенести»; the app's is in test_mobile."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Booking, Business, Conversation, Message, PanelUser, Slot, Staff, WaitlistEntry
from joop.reschedule import reschedule
from joop.security import hash_password
from joop.timeutil import utc_to_local
from joop.web.app import _login_fails, create_app

from .conftest import NOW_UTC
from .test_mobile import _chat_booking, book, tomorrow_slots
from .test_web import client, csrf_of, login  # noqa: F401  (fixture)


def _waiting(business_id, day, chat="w1"):
    """Someone who wanted a time on `day` and was told there was none."""
    with db.new_session() as s:
        conv = Conversation(business_id=business_id, channel="telegram", chat_id=chat, customer_name="Айбек")
        s.add(conv)
        s.flush()
        s.add(WaitlistEntry(business_id=business_id, conversation_id=conv.id, customer_name="Айбек", channel="telegram",
                            chat_id=chat, day=day, service="чистка"))
        s.commit()


def test_the_panel_moves_a_booking_tells_the_customer_and_offers_the_old_time_to_those_waiting(client, business, rt):  # noqa: F811
    slots = tomorrow_slots(business.id)
    old, new = slots[0], slots[3]
    booking_id = _chat_booking(business.id, old)
    _waiting(business.id, old.start.date())
    token = login(client)
    assert f'href="/panel/bookings/{booking_id}/move"' in client.get("/panel/bookings").text
    picker = client.get(f"/panel/bookings/{booking_id}/move").text
    assert "Сейчас:" in picker and "Айгуль" in picker
    assert f'name="slot_id" value="{new.id}"' in picker and f'value="{old.id}"' not in picker  # her own time is not "another"

    r = client.post(f"/panel/bookings/{booking_id}/move", data={"csrf": token, "slot_id": new.id})
    assert "Запись перенесена на" in r.text and "Клиенту написали в чат." in r.text
    sent = dict((chat, text) for chat, text, *_ in rt.tg.sent)
    assert "перенесена" in sent["9001"] and new.start.strftime("%H:%M") in sent["9001"]
    assert "освободилось время" in sent["w1"] and old.start.strftime("%H:%M") in sent["w1"]  # the waiting list hears of the old time
    with db.new_session() as s:
        moved = s.get(Booking, booking_id)
        assert (moved.slot_id, moved.start, moved.status) == (new.id, new.start, "booked")
        assert (moved.reminder_status, moved.confirmed_at) == ("", None)  # both were about the old time
        assert moved.conversation_id is not None and moved.service == "Консультация"  # the same booking, not a new one
        assert s.get(Slot, old.id).status == "free" and s.get(Slot, new.id).status == "booked"
        assert len(s.exec(select(Booking).where(Booking.business_id == business.id)).all()) == 1


def test_a_taken_time_goes_back_to_the_picker_and_altegio_or_cancelled_bookings_are_not_moved(client, business):  # noqa: F811
    slots = tomorrow_slots(business.id)
    booking_id = _chat_booking(business.id, slots[0])
    in_altegio = book(business.id, slots[1], name="Бакыт")
    with db.new_session() as s:
        row = s.get(Booking, in_altegio)
        row.external_id = "123"
        s.add(row)
        s.commit()
    token = login(client)
    day = slots[1].start.date().isoformat()
    r = client.post(f"/panel/bookings/{booking_id}/move", data={"csrf": token, "slot_id": slots[1].id}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/panel/bookings/{booking_id}/move?day={day}"
    assert "Это время уже занято" in client.get(r.headers["location"]).text
    assert client.post(f"/panel/bookings/{booking_id}/move", data={"csrf": "forged", "slot_id": slots[4].id}).status_code == 403
    assert client.post(f"/panel/bookings/{booking_id}/move", data={"csrf": token, "slot_id": 10**9}).status_code == 404

    assert f'href="/panel/bookings/{in_altegio}/move"' not in client.get("/panel/bookings").text  # moved in Altegio
    r = client.get(f"/panel/bookings/{in_altegio}/move", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/panel/bookings"
    assert "перенесите её там" in client.get("/panel/bookings").text
    r = client.post(f"/panel/bookings/{in_altegio}/move", data={"csrf": token, "slot_id": slots[4].id}, follow_redirects=False)
    assert r.headers["location"] == "/panel/bookings"

    client.post(f"/panel/bookings/{booking_id}/cancel", data={"csrf": token})
    r = client.get(f"/panel/bookings/{booking_id}/move", follow_redirects=False)
    assert r.status_code == 303 and "переносить нечего" in client.get("/panel/bookings").text
    with db.new_session() as s:
        assert s.get(Slot, slots[4].id).status == "free" and s.get(Booking, in_altegio).slot_id == slots[1].id


def test_the_picker_walks_days_but_not_into_the_past(client, business):  # noqa: F811
    booking_id = _chat_booking(business.id, tomorrow_slots(business.id)[0])
    login(client)
    today = utc_to_local(NOW_UTC, "Asia/Bishkek").date()
    page = client.get(f"/panel/bookings/{booking_id}/move", params={"day": "2020-01-01"}).text  # clamped to today
    assert today.strftime("%d.%m.%Y") in page and "?day=" + (today - timedelta(days=1)).isoformat() not in page
    assert "?day=" + (today + timedelta(days=1)).isoformat() in page
    far = client.get(f"/panel/bookings/{booking_id}/move", params={"day": "9999-12-31"})
    assert far.status_code == 200 and "свободного времени нет" in far.text
    assert client.get(f"/panel/bookings/{booking_id}/move", params={"day": "не дата"}).status_code == 200


def test_a_master_moves_her_booking_only_within_her_own_times(business, rt, settings):
    _login_fails.clear()
    slots = tomorrow_slots(business.id)
    mine = slots[0]
    hers_later = next(x for x in slots if x.staff_id == mine.staff_id and x.id != mine.id)
    other = next(x for x in slots if x.staff_id != mine.staff_id)
    booking_id = _chat_booking(business.id, mine)
    theirs = book(business.id, other, name="Бакыт")
    with db.new_session() as s:
        s.add(PanelUser(business_id=business.id, name="Мастер", login="master", password_hash=hash_password("staff-pass-1"),
                        staff_id=mine.staff_id))
        s.commit()
        free_of_others = [x.id for x in s.exec(select(Slot).where(Slot.business_id == business.id, Slot.status == "free",
                                                                   Slot.staff_id != mine.staff_id)).all()]
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        assert c.post("/login", data={"slug": "aktish", "user": "master", "password": "staff-pass-1", "csrf": token},
                      follow_redirects=False).status_code == 303
        picker = c.get(f"/panel/bookings/{booking_id}/move").text
        assert f'value="{hers_later.id}"' in picker and not any(f'name="slot_id" value="{i}"' in picker for i in free_of_others)
        assert "/panel/slots" not in picker  # the slots page is the owner's
        token = csrf_of(picker)
        assert c.get(f"/panel/bookings/{theirs}/move").status_code == 404
        assert c.post(f"/panel/bookings/{booking_id}/move", data={"csrf": token, "slot_id": free_of_others[0]}).status_code == 404
        r = c.post(f"/panel/bookings/{booking_id}/move", data={"csrf": token, "slot_id": hers_later.id}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/panel/bookings"
    with db.new_session() as s:
        assert s.get(Booking, booking_id).slot_id == hers_later.id
    _login_fails.clear()


def test_a_kyrgyz_chat_is_told_in_kyrgyz_and_a_booking_without_a_chat_is_not_told(business, rt):
    slots = tomorrow_slots(business.id)
    booking_id, by_hand = _chat_booking(business.id, slots[0]), book(business.id, slots[1], name="Бакыт", channel="")
    now_local = utc_to_local(NOW_UTC, "Asia/Bishkek")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        chat = s.get(Booking, booking_id)
        s.add(Message(business_id=b.id, conversation_id=chat.conversation_id, role="customer", text="Эртең саат 10го жазып коюңузчу"))
        s.flush()
        moved = reschedule(s, rt, b, chat, s.get(Slot, slots[3].id), now_local, NOW_UTC)
        assert moved.problem == "" and moved.told is True
        assert "жылдырылды" in rt.tg.sent[-1][1] and s.get(Staff, slots[3].staff_id).name in rt.tg.sent[-1][1]
        count = len(rt.tg.sent)
        quiet = reschedule(s, rt, b, s.get(Booking, by_hand), s.get(Slot, slots[4].id), now_local, NOW_UTC)
        assert quiet.problem == "" and quiet.told is False and len(rt.tg.sent) == count  # staff call this customer themselves
        again = reschedule(s, rt, b, s.get(Booking, by_hand), s.get(Slot, slots[4].id), now_local, NOW_UTC)
        assert again.problem == "Это то же самое время."
        s.commit()


def test_only_a_visit_that_has_not_happened_moves(client, business):  # noqa: F811
    """A paid visit stays on its day in the cash; a visit of hours ago is over; a customer who is late still moves."""
    slots = tomorrow_slots(business.id)
    now_local = utc_to_local(NOW_UTC, "Asia/Bishkek")  # Wed 4 Nov 23:14
    paid = book(business.id, slots[0])
    with db.new_session() as s:
        member = s.exec(select(Staff).where(Staff.business_id == business.id)).first()
        row = s.get(Booking, paid)
        row.paid_som, row.paid_method = 1500, "cash"
        over = Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=now_local - timedelta(hours=3),
                       customer_name="Вчерашний", channel="")
        late = Booking(business_id=business.id, staff_id=member.id, staff_name=member.name, start=now_local - timedelta(minutes=40),
                       customer_name="Опаздывает", channel="")
        s.add_all([row, over, late])
        s.commit()
        over_id, late_id = over.id, late.id
    token = login(client)
    page = client.get("/panel/bookings").text
    assert f'href="/panel/bookings/{late_id}/move"' in page
    assert f'href="/panel/bookings/{paid}/move"' not in page and f'href="/panel/bookings/{over_id}/move"' not in page
    for booking_id, word in ((paid, "уже отмечена оплата"), (over_id, "Этот визит уже прошёл")):
        r = client.post(f"/panel/bookings/{booking_id}/move", data={"csrf": token, "slot_id": slots[3].id}, follow_redirects=False)
        assert r.headers["location"] == "/panel/bookings" and word in client.get("/panel/bookings").text
    r = client.post(f"/panel/bookings/{late_id}/move", data={"csrf": token, "slot_id": slots[3].id})
    assert "Запись перенесена на" in r.text and "Сообщите клиенту сами" in r.text  # booked by hand: no chat to write to
    with db.new_session() as s:
        assert s.get(Booking, late_id).start == slots[3].start and s.get(Booking, paid).start == slots[0].start
        assert s.get(Booking, over_id).slot_id is None and s.get(Slot, slots[3].id).status == "booked"


def test_a_booking_awaiting_prepayment_does_not_move_to_before_its_deadline(business, rt):
    """Otherwise the deadline would fall after the visit, and auto-cancel would drop the booking staff just moved."""
    slots = tomorrow_slots(business.id)
    booking_id = _chat_booking(business.id, slots[5])
    now_local = utc_to_local(NOW_UTC, "Asia/Bishkek")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        row = s.get(Booking, booking_id)
        row.deposit_due, row.deposit_status = 500, "awaiting"
        row.deposit_deadline = NOW_UTC + timedelta(hours=12)  # 05:14 UTC tomorrow = 11:14 in Bishkek
        s.add(row)
        s.flush()
        early = reschedule(s, rt, b, row, s.get(Slot, slots[0].id), now_local, NOW_UTC)  # 09:00 tomorrow: before the deadline
        assert "ждём предоплату до 05.11.2026 11:14" in early.problem and row.slot_id == slots[5].id
        assert s.get(Slot, slots[0].id).status == "free"
        later = next(x for x in s.exec(select(Slot).where(Slot.business_id == b.id, Slot.status == "free").order_by(Slot.start)).all()
                     if x.start > utc_to_local(row.deposit_deadline, "Asia/Bishkek") + timedelta(hours=1))
        moved = reschedule(s, rt, b, row, later, now_local, NOW_UTC)
        assert moved.problem == "" and row.slot_id == later.id and row.deposit_status == "awaiting"
        s.commit()


def test_two_quick_moves_of_one_booking_do_not_free_a_time_given_to_someone_else(business, rt):
    """Two «перенести» presses read the booking at its old time; the second must not free that time again."""
    slots = tomorrow_slots(business.id)
    booking_id = book(business.id, slots[0], name="Айгерим", channel="")
    now_local = utc_to_local(NOW_UTC, "Asia/Bishkek")
    with db.new_session() as late:  # the second press: read before the first one finished
        stale = late.get(Booking, booking_id)
        assert stale.slot_id == slots[0].id
        with db.new_session() as s:  # the first press moves it to slots[1]
            assert reschedule(s, rt, s.get(Business, business.id), s.get(Booking, booking_id), s.get(Slot, slots[1].id),
                              now_local, NOW_UTC).problem == ""
            s.commit()
        other = book(business.id, slots[0], name="Бакыт", channel="")  # the AI gives the freed time to someone else
        moved = reschedule(late, rt, late.get(Business, business.id), stale, late.get(Slot, slots[2].id), now_local, NOW_UTC)
        late.commit()
        assert "только что изменили" in moved.problem
    with db.new_session() as s:
        assert s.get(Booking, booking_id).slot_id == slots[1].id and s.get(Booking, other).slot_id == slots[0].id
        assert s.get(Slot, slots[0].id).status == "booked"  # still Бакыт's, not freed by the second press
        assert s.get(Slot, slots[2].id).status == "free"  # the second press gave back the time it had claimed


def test_a_party_does_not_move_to_a_smaller_table(business, rt):
    slots = tomorrow_slots(business.id)
    booking_id = book(business.id, slots[0], name="Айгерим", channel="")
    now_local = utc_to_local(NOW_UTC, "Asia/Bishkek")
    with db.new_session() as s:
        small = s.get(Staff, slots[3].staff_id)
        small.capacity = 2
        row = s.get(Booking, booking_id)
        row.party_size = 6
        s.add_all([small, row])
        s.flush()
        moved = reschedule(s, rt, s.get(Business, business.id), row, s.get(Slot, slots[3].id), now_local, NOW_UTC)
        assert moved.problem.startswith("Этот стол рассчитан на 2 гостей") and row.slot_id == slots[0].id
        assert s.get(Slot, slots[3].id).status == "free"


def test_a_booking_does_not_move_into_a_master_whose_schedule_comes_from_altegio(business, rt):
    """Altegio still shows that time free: its next sync would cancel the booking Joop had moved there."""
    slots = tomorrow_slots(business.id)
    booking_id = book(business.id, slots[0], name="Айгерим", channel="")
    now_local = utc_to_local(NOW_UTC, "Asia/Bishkek")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.altegio_location_id = "123"
        member = s.get(Staff, slots[3].staff_id)
        member.external_id = "7"
        s.add_all([b, member])
        s.flush()
        moved = reschedule(s, rt, b, s.get(Booking, booking_id), s.get(Slot, slots[3].id), now_local, NOW_UTC)
        assert "ведётся в Altegio" in moved.problem and s.get(Booking, booking_id).slot_id == slots[0].id
        assert s.get(Slot, slots[3].id).status == "free"
