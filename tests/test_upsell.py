"""One add-on offered by code right after a booking (joop/upsell.py)."""

from datetime import datetime, timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Message, Service
from joop.scheduler import monthly_report_text
from joop.timeutil import local_to_utc

from .conftest import NOW_UTC, FakeLLM, first_free_slot
from .test_web import client, csrf_of, login  # noqa: F401  (client is a fixture)


def pair(business_id, base_name="Консультация и осмотр", addon_name="Профессиональная чистка", addon_ky=""):
    """Make the price list offer `addon` with `base`; returns (base, addon) as (name, price)."""
    with db.new_session() as s:
        services = s.exec(select(Service).where(Service.business_id == business_id)).all()
        base = next(x for x in services if x.name == base_name)
        addon = next(x for x in services if x.name == addon_name)
        addon.price, addon.price_value, addon.name_ky = "3 500", 3500, addon_ky
        base.upsell_id = addon.id
        s.add_all([base, addon])
        s.commit()
        return base.name, addon.name


def say(business_id, rt, text, now=NOW_UTC, chat="c1"):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text), rt.get_llm, now)
        s.commit()
        return out


def book(business_id, rt, service="консультация", first="Запишите, Айбек, 0555 123 456"):
    slot = first_free_slot(business_id)
    rt._llm = FakeLLM([AgentReply("Записала!", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555 123 456",
                                                         "service": service})])
    return say(business_id, rt, first)


def test_offer_after_booking_and_yes_adds_it(business, rt):
    pair(business.id)
    out = book(business.id, rt)
    assert out.reply == "Записала!\n\nХотите добавить «Профессиональная чистка» — 3 500 сом? Ответьте «да», и я добавлю к записи."
    yes = say(business.id, rt, "Да, давайте!", now=NOW_UTC + timedelta(minutes=5))
    assert yes.reply.startswith("Добавила «Профессиональная чистка» к вашей записи на ")
    assert yes.admin_notes[0].startswith("Допродажа: Айбек") and "+3 500 сом" in yes.admin_notes[0] and "хватает ли времени" in yes.admin_notes[0]
    assert len(rt._llm.calls) == 1  # the answer needed no model call
    with db.new_session() as s:
        b = s.exec(select(Booking)).one()
        assert (b.service, b.upsell_status, b.upsell_price) == ("консультация + Профессиональная чистка", "accepted", 3500)
    rt._llm.replies.append(AgentReply("Пожалуйста!"))
    assert say(business.id, rt, "да", now=NOW_UTC + timedelta(minutes=6)).reply == "Пожалуйста!"  # offered once


def test_no_closes_it_and_other_messages_go_to_the_ai(business, rt):
    pair(business.id)
    book(business.id, rt)
    rt._llm.replies.append(AgentReply("Чистка занимает час."))
    assert say(business.id, rt, "А сколько длится чистка?").reply == "Чистка занимает час."
    rt._llm.replies.append(AgentReply("Хорошо."))
    assert say(business.id, rt, "да").reply == "Хорошо."  # the AI spoke since the offer: this "да" is for the AI
    with db.new_session() as s:
        assert s.exec(select(Booking.upsell_status)).one() == "offered"


def test_no_and_kyrgyz(business, rt):
    pair(business.id, addon_ky="Тиш тазалоо")
    out = book(business.id, rt, first="Жазып коюңузчу, Айбек, 0555 123 456")
    assert out.reply.endswith("\n\nЖазылууга «Тиш тазалоо» кошуп коёлубу — 3 500 сом? «Ооба» деп жооп бериңиз.")
    no = say(business.id, rt, "Жок, рахмат")
    assert no.reply == "Макул, жазылуу ошол бойдон калат." and no.admin_notes == []
    with db.new_session() as s:
        assert s.exec(select(Booking.upsell_status)).one() == "declined"


def test_not_offered_with_prepayment_late_or_without_exact_price(business, rt):
    pair(business.id)
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.deposit_amount, b.deposit_details = 500, "MBank 0555 000 111"
        s.add(b)
        s.commit()
    out = book(business.id, rt)
    assert "предоплата" in out.reply and "Хотите добавить" not in out.reply  # one message asks one thing
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.deposit_amount = 0
        addon = s.exec(select(Service).where(Service.name == "Профессиональная чистка")).one()
        addon.price_value = None
        s.add_all([b, addon])
        s.commit()
    assert "Хотите добавить" not in book(business.id, rt, first="Запишите ещё раз, Айбек, 0555 123 456").reply


def test_answer_window(business, rt):
    pair(business.id)
    book(business.id, rt)
    rt._llm.replies.append(AgentReply("Слушаю."))
    assert say(business.id, rt, "да", now=NOW_UTC + timedelta(hours=3)).reply == "Слушаю."


def test_monthly_report_counts_add_ons(business):
    base, addon = pair(business.id)
    when = local_to_utc(datetime(2026, 10, 15, 12, 0), business.timezone)
    with db.new_session() as s:
        price = s.exec(select(Service.price_value).where(Service.name == base)).one()
        conv = Conversation(business_id=business.id, channel="telegram", chat_id="m1", created_at=when)
        s.add(conv)
        s.flush()
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="customer", text="?", created_at=when))
        s.add(Booking(business_id=business.id, start=datetime(2026, 10, 16, 10, 0), service=f"{base} + {addon}", source="ai",
                      upsell_status="accepted", upsell_service=addon, upsell_price=3500, created_at=when))
        s.commit()
        text = monthly_report_text(s, s.get(Business, business.id), local_to_utc(datetime(2026, 11, 1, 10, 0), business.timezone))
    assert "Допродажа: 1 дополнительная услуга к записям — ещё 3 500 сом." in text
    assert f"около {price + 3500:,} сом".replace(",", " ") in text  # the base price plus the add-on


def test_panel_setting(client, business):  # noqa: F811
    login(client)
    page = client.get("/panel/services").text
    assert "Что предложить к записи" in page
    with db.new_session() as s:
        services = s.exec(select(Service).where(Service.business_id == business.id)).all()
        base = next(x for x in services if x.name == "Консультация и осмотр")
        target = next(x for x in services if x.price_value and x.id != base.id)
        unpriced = next((x for x in services if not x.price_value), None)
    client.post("/panel/services/upsell", data={"csrf": csrf_of(page), f"upsell_{base.id}": str(target.id),
                                                f"upsell_{target.id}": str(target.id)})  # itself: refused
    with db.new_session() as s:
        assert s.get(Service, base.id).upsell_id == target.id and s.get(Service, target.id).upsell_id == 0
    if unpriced:
        client.post("/panel/services/upsell", data={"csrf": csrf_of(page), f"upsell_{base.id}": str(unpriced.id)})
        with db.new_session() as s:
            assert s.get(Service, base.id).upsell_id == 0  # only a service with an exact price
