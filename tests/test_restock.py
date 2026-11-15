"""«Напишем, когда появится» (joop/restock.py): a sold-out item asked for is announced once when it is back."""

from datetime import timedelta

from sqlmodel import select

from joop import db, restock, stock
from joop.agent.llm import AgentReply
from joop.models import Business, Conversation, Message, Service, StockWatch

from .conftest import NOW_UTC, FakeLLM
from .test_holds import with_bot
from .test_pharmacy import pharmacy


def ask(business_id, text, ext, chat="c1"):
    from joop.agent.engine import handle_incoming
    from joop.channels.base import IncomingMessage

    llm = FakeLLM([AgentReply("Масок сейчас нет в наличии.")])
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
    return out


def masks(business_id):
    with db.new_session() as s:
        return s.exec(select(Service).where(Service.business_id == business_id, Service.name == "Маски медицинские, 50 шт.")).one()


def restock_masks(business_id, qty=20):
    with db.new_session() as s:
        stock.recount(s, s.get(Service, masks(business_id).id), qty, 0, "Гульнара", NOW_UTC + timedelta(days=2))
        s.commit()


def run(rt, business_id, when):
    with db.new_session() as s:
        out = restock.notify_back(s, rt, s.get(Business, business_id), when)
        s.commit()
        return out


def test_asking_for_a_sold_out_item_keeps_a_watch_and_says_so(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    assert masks(b.id).sold_out  # the demo has 0 masks
    out = ask(b.id, "Медицинские маски есть?", "a")
    assert out.reply.endswith("Когда «Маски медицинские, 50 шт.» снова появится, напишем вам сюда. Не нужно — напишите «стоп».")
    ask(b.id, "А маски когда будут?", "b")  # asked again: still one watch
    with db.new_session() as s:
        assert len(s.exec(select(StockWatch)).all()) == 1
    assert run(rt, b.id, NOW_UTC + timedelta(days=1)) == {}  # still out
    restock_masks(b.id)
    assert run(rt, b.id, NOW_UTC + timedelta(days=2, hours=1)) == {"sent": 1}
    chat, text = rt.tg.sent[-1]
    assert chat == "c1" and text == "«Маски медицинские, 50 шт.» снова в наличии, цена 250. Отложить для вас?"
    assert run(rt, b.id, NOW_UTC + timedelta(days=3)) == {}  # once


def test_items_in_stock_and_unrelated_words_keep_no_watch(engine, rt):
    b = pharmacy()
    assert "напишем вам сюда" not in ask(b.id, "Парацетамол есть?", "a").reply  # in stock
    assert "напишем вам сюда" not in ask(b.id, "Где вы находитесь?", "b", chat="c2").reply
    assert [i.id for i in restock.asked_for("маска нужна", [masks(b.id)])] == [masks(b.id).id]  # «маска» / «маски» / «масок»
    assert restock.asked_for("Маскалар барбы?", [masks(b.id)])  # Kyrgyz plural


def test_stopped_items_old_watches_and_silenced_chats_get_nothing(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    ask(b.id, "Маски есть?", "a")
    ask(b.id, "Маски нужны", "b", chat="c2")
    ask(b.id, "Маски бар?", "c", chat="c3")
    with db.new_session() as s:
        convs = {c.chat_id: c for c in s.exec(select(Conversation).where(Conversation.business_id == b.id)).all()}
        convs["c2"].broadcast_opt_out = True  # said «стоп»
        old = s.exec(select(StockWatch).where(StockWatch.conversation_id == convs["c3"].id)).one()
        old.created_at = NOW_UTC - timedelta(days=31)
        s.commit()
    sent_before = len(rt.tg.sent)
    restock_masks(b.id)
    assert run(rt, b.id, NOW_UTC + timedelta(days=2, hours=1)) == {"sent": 1, "expired": 1}
    assert [chat for chat, _ in rt.tg.sent[sent_before:]] == ["c1"]


def test_an_item_the_owner_stopped_selling_is_not_announced(engine, rt):
    b = pharmacy()
    with_bot(b.id)
    ask(b.id, "Маски есть?", "a")
    restock_masks(b.id)
    with db.new_session() as s:
        item = s.get(Service, masks(b.id).id)
        item.available = False  # the owner took it off sale after the count
        s.commit()
    assert run(rt, b.id, NOW_UTC + timedelta(days=2, hours=1)) == {}
    with db.new_session() as s:
        assert not s.exec(select(Message).where(Message.text.contains("снова в наличии"))).all()
