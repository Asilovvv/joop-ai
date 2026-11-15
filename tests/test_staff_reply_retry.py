"""A staff reply retried by the app or sent twice by a double tap reaches the customer once."""

from datetime import timedelta

from sqlmodel import select

from joop import db, staff_reply
from joop.models import Business, Conversation, Message

from .conftest import NOW_UTC


def test_the_same_reply_within_minutes_is_sent_once(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token = "123:TEST"
        conv = Conversation(business_id=b.id, channel="telegram", chat_id="t1", created_at=NOW_UTC)
        s.add(conv)
        s.commit()
        for when in (NOW_UTC, NOW_UTC + timedelta(seconds=95)):  # the app's 90-second timeout, then a retry
            assert staff_reply.send(s, rt, b, conv, "Здравствуйте! Свободно в 15:00.", when, author="Айгуль") == (True, "")
            s.commit()
        assert [t for _, t in rt.tg.sent].count("Здравствуйте! Свободно в 15:00.") == 1
        staff_reply.send(s, rt, b, conv, "Здравствуйте! Свободно в 15:00.", NOW_UTC + timedelta(minutes=10), author="Айгуль")
        staff_reply.send(s, rt, b, conv, "Здравствуйте! Свободно в 15:00.", NOW_UTC + timedelta(minutes=10, seconds=5), author="Бакыт")
        s.commit()
        assert [t for _, t in rt.tg.sent].count("Здравствуйте! Свободно в 15:00.") == 3  # later, or another person: sent
        assert len(s.exec(select(Message).where(Message.conversation_id == conv.id, Message.role == "staff")).all()) == 3
