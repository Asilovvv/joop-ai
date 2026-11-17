"""Independent review of PRs #234-#240: each test failed before its fix."""

from fastapi.testclient import TestClient

from joop import db, samples
from joop.models import Business
from joop.presets import create_business
from joop.web.app import create_app
from joop.web.menu import order_link

from .conftest import NOW_UTC


def _fresh_restaurant(**changes) -> int:
    with db.new_session() as s:
        b = create_business(s, slug="fresh", name="Свежая", password="fresh-pass", niche="restaurant", demo=True,
                            now_utc=NOW_UTC)
        b.menu_enabled = True  # the owner turned on the public QR menu
        for k, v in changes.items():
            setattr(b, k, v)
        s.commit()
        return b.id


def test_pr238_public_menu_page_shows_the_sign_up_example_address_and_phone(settings, rt, engine):
    """/m/<slug> is read by real customers (QR on the table); #238 hid the example contacts everywhere else."""
    bid = _fresh_restaurant()
    with db.new_session() as s:
        b = s.get(Business, bid)
        hidden = samples.example_contacts(b)
        demo_address, demo_phone = b.address, b.phone
    assert {"address", "phone"} <= hidden  # precondition: these ARE the example's fictional contacts
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/m/fresh").text
    assert demo_address not in page, "fictional example address shown on the public menu"
    assert demo_phone not in page, "fictional example phone shown on the public menu"


def test_pr238_public_menu_order_button_dials_the_example_phone(engine):
    """With no chat link set, the menu's main button is wa.me/<business.phone>: the fictional example number."""
    bid = _fresh_restaurant()
    with db.new_session() as s:
        b = s.get(Business, bid)
        assert "phone" in samples.example_contacts(b)
        url, _ = order_link(b, "ru", None)
    digits = "".join(ch for ch in b.phone if ch.isdigit())
    assert digits not in url, f"order button leads to the example phone: {url}"


def test_a_kyrgyz_chat_is_counted_when_only_the_code_confirms(business):
    """The model booked but wrote nothing: the code's Kyrgyz confirmation is the reply, counted as Kyrgyz."""
    from sqlmodel import select

    from joop import db
    from joop.agent.llm import AgentReply
    from joop.models import Message, Slot

    from .conftest import FakeLLM
    from .test_kyrgyz_and_cost import say as ky_say

    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.status == "free").order_by(Slot.start)).first()
    booking = {"slot_id": slot.id, "name": "Гүлнара", "phone": "0555321654", "service": "чистка", "preferred_time": ""}
    out = ky_say(business, "Атым Гүлнара, 0555 321 654, эртең тиш тазалоо", FakeLLM([AgentReply("", booking=booking)]), "ke1")
    assert out.booking_id and out.reply
    with db.new_session() as s:
        last = s.exec(select(Message).where(Message.role == "ai").order_by(Message.id.desc())).first()
    assert last.kyrgyz == "ky"
