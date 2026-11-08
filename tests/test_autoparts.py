"""Auto parts (joop/niches/autoparts): compatibility from the catalog, special orders as leads, reserves that expire."""

from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Order
from joop.presets import create_business
from joop.scheduler import digest_text

from .conftest import NOW_UTC, FakeLLM


def parts_shop():
    with db.new_session() as s:
        b = create_business(s, slug="parts", name="Запчасти", password="parts-pass-1", niche="autoparts", demo=True, now_utc=NOW_UTC)
        b.example_ok = True
        s.commit()
        return b


def test_sold_out_part_and_special_order_questions_reach_the_prompt(engine):
    b = parts_shop()
    llm = FakeLLM([AgentReply("Уточните год.")])
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, b.id), IncomingMessage("telegram", "p1", "text", "Колодки на Элантру есть?", "", "p1"),
                        lambda: llm, NOW_UTC)
        s.commit()
    system = llm.calls[0]["system"]
    assert "Сейчас нет в наличии (не предлагай): Колодки тормозные передние Hyundai Elantra (2016–2020)" in system
    assert "марка, модель и год, VIN или номер детали" in system


def test_digest_lists_reserves_nobody_collected(engine):
    b = parts_shop()
    with db.new_session() as s:
        test_chat = Conversation(business_id=b.id, channel="console", chat_id="panel-test", created_at=NOW_UTC)
        s.add(test_chat)
        s.flush()
        old = NOW_UTC - timedelta(hours=30)
        rows = [("Эркин", "pickup", "new", old, None), ("Самат", "pickup", "accepted", old, None),
                ("Бекзат", "delivery", "new", old, None), ("Айбек", "pickup", "done", old, None),
                ("Свежий", "pickup", "new", NOW_UTC - timedelta(hours=2), None), ("Тест", "pickup", "new", old, test_chat.id)]
        for name, mode, status, when, conv in rows:
            s.add(Order(business_id=b.id, customer_name=name, customer_phone="+996555000000", mode=mode, status=status,
                        channel="console" if conv else "telegram", conversation_id=conv, created_at=when))
        s.commit()
        text = digest_text(s, s.get(Business, b.id), NOW_UTC)
        ids = {o.customer_name: o.id for o in s.exec(select(Order).where(Order.business_id == b.id)).all()}
    line = next(x for x in text.split("\n") if x.startswith("Самовывоз не забрали больше суток:"))
    assert f"№{ids['Эркин']} (Эркин), №{ids['Самат']} (Самат)" in line and "вернулся в продажу" in line
    assert not any(n in line for n in ("Бекзат", "Айбек", "Свежий", "Тест"))
