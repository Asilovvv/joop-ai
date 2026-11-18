"""No real customer reads the sign-up example, in any niche, whichever way the words reach them (joop/samples.py).

A business that still holds the whole example connects its bot: a demo the founder made for a prospect, which is
sign-up's example plus the example's address, phone, description, booking policy and order terms. The test walks what
a customer can read — what the AI is told and what the code writes in Telegram and in the site chat, the public menu,
the chat page, the app's place card, MCP, ready answers, two days of scheduled messages — and looks for the example's
own words. The owner's test chat keeps the example: there it is the point.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, quick_replies
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Service, Slot, Staff
from joop.niches import all_packs, get_pack
from joop.presets import create_business
from joop.profile import load_profile
from joop.scheduler import run_due_jobs
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM


def _t(value) -> str:
    return " ".join(str(value or "").split())


def example_words(niche: str) -> dict[str, str]:
    """The example's own words by what they are. Words the pack's rules use too («Пробный урок — это запись…») say
    nothing about the example and are left out."""
    pack = get_pack(niche)
    demo = load_profile(pack.demo_file)
    rules = _t(Path(pack.demo_file).with_name("pack.yaml").read_text(encoding="utf-8"))
    out = {key: _t(demo.get(key)) for key in ("address", "phone", "hours", "description", "booking_policy")}
    for x in demo.get("services") or []:
        out[f"price list: {x['name']}"] = _t(x["name"])
        out[f"note of {x['name']}"] = _t(x.get("note"))
    for x in demo.get("resources") or []:
        out[f"person: {x['name']}"] = _t(x["name"])
    for x in demo.get("faq") or []:
        out[f"answer to «{x['q']}»"] = _t(x["a"])
    for x in demo.get("jobs") or []:
        out[f"receipt {x['number']}"] = _t(x["item"])
    if demo.get("min_order"):
        out["minimum order"] = f"минимальная сумма заказа {demo['min_order']} сом"
    if demo.get("delivery_fee"):
        out["delivery fee"] = f"доставка {demo['delivery_fee']} сом"
    if demo.get("free_delivery_from"):
        out["free delivery"] = f"бесплатная доставка от {demo['free_delivery_from']} сом"
    return {key: words for key, words in out.items() if words and words not in rules}


@pytest.mark.parametrize("niche", sorted(all_packs()))
def test_a_real_customer_reads_nothing_of_the_example(niche, settings, rt, engine):
    with db.new_session() as s:
        b = create_business(s, slug="demo", name="Настоящая фирма", password="demo-pass-1", niche=niche, demo=True, now_utc=NOW_UTC)
        b.telegram_bot_token, b.telegram_bot_username, b.menu_enabled = "123:TEST", "demo_bot", True
        s.commit()
        bid = b.id
        slot = s.exec(select(Slot).where(Slot.business_id == bid, Slot.status == "free").order_by(Slot.start)).first()
        item = s.exec(select(Service).where(Service.business_id == bid).order_by(Service.sort)).first()
        room = s.exec(select(Staff).where(Staff.business_id == bid).order_by(Staff.id)).first()
        slot_id, item_id, item_name, room_name = (slot.id if slot else None), item.id, item.name, (room.name if room else "")
    pack, demo, read = get_pack(niche), load_profile(get_pack(niche).demo_file), {}

    def say(label, text, reply=None, channel="telegram"):
        llm = FakeLLM([reply or AgentReply("Здравствуйте!")])
        with db.new_session() as s:
            out = handle_incoming(s, s.get(Business, bid), IncomingMessage(channel, label, "text", text, "Клиент", label),
                                  lambda: llm, NOW_UTC, base_url="https://joop.test")
            s.commit()
        read[f"what the AI is told ({label})"] = llm.calls[0]["system"] if llm.calls else ""
        read[f"the reply ({label})"] = out.reply or ""

    contacts = {"name": "Айбек", "phone": "0555123456"}
    say("hello", "Здравствуйте! Сколько стоит, где вы находитесь и как работаете? Есть доставка?")
    say("kyrgyz", "Саламатсызбы! Баасы канча, дарегиңиз кайда?")
    say("start", "/start")
    for job in demo.get("jobs") or []:  # a customer whose phone happens to be a demo receipt's
        say(f"receipt {job['number']}", f"Готов ли мой заказ №{job['number']}? Мой телефон {job['phone']}")
    for i, x in enumerate(demo.get("services") or []):
        if x.get("stock") == 0 or x.get("available") is False:
            say(f"sold out {i}", f"Здравствуйте, {x['name']} есть?")
    if pack.has("booking") and slot_id:
        say("booking", "Запишите меня. Айбек, 0555123456",
            AgentReply("Записал вас.", booking={"slot_id": slot_id, "service": item_name, **contacts}))
    if pack.has("order"):
        say("order", "Хочу заказать с доставкой на Киевскую 10. Айбек, 0555123456",
            AgentReply("Заказ принят.", order={"lines": [{"item_id": item_id, "quantity": 1}], "mode": "delivery",
                                               "address": "Киевская 10", **contacts}))
    if pack.has("stay"):
        say("stay", "Забронируйте. Айбек, 0555123456",
            AgentReply("Забронировал.", stay={"room": room_name, "check_in": "2026-11-10", "check_out": "2026-11-12",
                                              "guests": 2, **contacts}))
    with db.new_session() as s:  # the sold-out example goods are back on the shelf: nobody is told about them
        for row in s.exec(select(Service).where(Service.business_id == bid, Service.sold_out == True)).all():  # noqa: E712
            row.stock, row.sold_out, row.available = 5, False, True
            s.add(row)
        s.commit()
    for hours in range(0, 48, 3):
        with db.new_session() as s:
            run_due_jobs(s, rt, s.get(Business, bid), NOW_UTC + timedelta(hours=hours))
            s.commit()
    read["scheduled messages"] = "\n".join(text for _, text in rt.tg.sent)

    rt._llm = FakeLLM([AgentReply("Здравствуйте!")])
    with TestClient(create_app(settings, rt, init=False)) as c:
        for path in ("/m/demo", "/m/demo?lang=ky", "/c/demo", "/c/demo/widget.js", "/api/mobile/places/demo"):
            page = c.get(path)
            assert page.status_code == 200, path
            read[path] = page.text
        read["the site chat's reply"] = c.post("/c/demo/chat", json={"text": "Где вы и сколько стоит?", "visitor": ""}).text
        read["what the AI is told (site chat)"] = rt._llm.calls[0]["system"]
    with db.new_session() as s:
        b = s.get(Business, bid)
        read["a ready answer"] = quick_replies.fill("Мы по адресу: {адрес}. Телефон: {телефон}. {компания}", b)
        from joop.mcp import business_info

        read["MCP"] = str(business_info(s, b))

    words = example_words(niche)
    found = sorted({f"{what} «{text}» in {where}" for what, text in words.items() for where, got in read.items() if text in got})
    assert not found, "\n".join(found)

    say("console", "Сколько стоит и где вы находитесь?", channel="console")  # the owner's test chat: the example is the point
    told = read["what the AI is told (console)"]
    assert all(text in told for what, text in words.items() if what in ("address", "hours", "booking_policy", "delivery fee")
               or what.startswith("price list")), niche
