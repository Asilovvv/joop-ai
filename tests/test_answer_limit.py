"""A chat that makes the AI answer too often is handed to staff (joop/agent/engine.py: _answers_spent).

Another business's auto-reply or a bot answers every message of ours, and so does a person who is only playing:
each answer is a paid model call. Before this limit one such chat could spend without end; the queue of #275 keeps
the server alive but reads every message.
"""

from datetime import timedelta

from sqlmodel import select

from joop import db, faq_gaps, funnel, nudges
from joop.agent import engine
from joop.agent.engine import HANDED_OVER_REPLY, handle_incoming
from joop.agent.llm import AgentReply
from joop.api import LEAD_KINDS
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, ConversationNote, Lead, Message
from joop.stats import TEST_CHANNEL

from .conftest import NOW_UTC, FakeLLM


class Always(FakeLLM):
    def respond(self, system, messages, schema=None):
        self.calls.append(messages[-1]["content"])
        return AgentReply(f"Ответ {len(self.calls)}.")


def say(business_id, llm, text, when, chat="700", channel="telegram", ext=None):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "Айбек", ext or f"m{when.timestamp()}{text}"),
                              lambda: llm, when)
        s.commit()
        return out


def chat(business_id, llm, count, start, every=timedelta(seconds=30), **kw):
    """`count` messages, each answered by the model; returns the time of the last one."""
    when = start
    for i in range(count):
        when = start + every * i
        assert say(business_id, llm, f"вопрос {i}", when, **kw).reply, i
    return when


def conv_of(business_id, chat="700"):
    with db.new_session() as s:
        return s.exec(select(Conversation).where(Conversation.business_id == business_id, Conversation.chat_id == chat)).one()


def stops(business_id):
    with db.new_session() as s:
        return s.exec(select(Lead).where(Lead.business_id == business_id, Lead.kind == "limit").order_by(Lead.id)).all()


def test_a_chat_that_makes_the_ai_answer_too_often_is_handed_to_staff(business):
    llm = Always()
    last = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC)
    assert len(llm.calls) == 60 and stops(business.id) == []  # sixty answers in half an hour: all given
    at = last + timedelta(seconds=30)
    out = say(business.id, llm, "и ещё вопрос", at)
    assert out.reply == HANDED_OVER_REPLY and len(llm.calls) == 60  # the model is not asked
    assert conv_of(business.id).ai_paused_until == at + timedelta(hours=1)
    (stop,) = stops(business.id)
    assert stop.summary.startswith("ИИ остановлен в этом чате на час: за последний час он ответил 60 раз.")
    assert "чужой бот" in stop.summary and "чёрный список" in stop.summary and stop.id == out.lead_id
    assert len(out.admin_notes) == 1 and "ИИ остановлен в этом чате на час" in out.admin_notes[0]
    # what comes next is neither answered nor sent to staff message by message: they were told once
    for i in range(5):
        quiet = say(business.id, llm, f"спам {i}", at + timedelta(seconds=10 * (i + 1)))
        assert quiet.skipped == "paused" and quiet.reply is None and quiet.admin_notes == []
    assert len(llm.calls) == 60 and len(stops(business.id)) == 1
    with db.new_session() as s:  # every message is still kept for whoever opens the dialogue, with the reason among them
        assert len(s.exec(select(Message).where(Message.role == "customer")).all()) == 66
        note = s.exec(select(ConversationNote)).one()
        assert note.text == stop.summary and note.author == "Joop AI" and note.created_at == at


def test_staff_who_take_the_chat_see_its_messages_again(business):
    llm = Always()
    at = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC) + timedelta(seconds=30)
    assert say(business.id, llm, "ещё", at).reply == HANDED_OVER_REPLY
    conv = conv_of(business.id)
    with db.new_session() as s:  # an administrator answers by hand from the panel
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="staff", text="Здравствуйте, это администратор.",
                      created_at=at + timedelta(minutes=2)))
        s.commit()
    out = say(business.id, llm, "спасибо, жду", at + timedelta(minutes=3))
    assert out.skipped == "paused" and len(out.admin_notes) == 1 and "спасибо, жду" in out.admin_notes[0]


def test_the_ai_comes_back_after_the_hour_and_a_second_stop_lasts_a_day(business):
    llm = Always()
    first = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC) + timedelta(seconds=30)
    assert say(business.id, llm, "ещё", first).reply == HANDED_OVER_REPLY
    back = first + timedelta(hours=1, seconds=1)
    assert say(business.id, llm, "вы тут?", back).reply == "Ответ 61."  # the hour passed: the AI answers again
    again = chat(business.id, llm, engine.ANSWERS_PER_HOUR - 1, back + timedelta(seconds=30)) + timedelta(seconds=30)
    out = say(business.id, llm, "ещё", again)
    assert out.reply == HANDED_OVER_REPLY and len(llm.calls) == 120
    assert conv_of(business.id).ai_paused_until == again + timedelta(hours=24)  # the same chat twice in a day: a bot, most likely
    assert [s.summary.split(":")[0] for s in stops(business.id)] == ["ИИ остановлен в этом чате на час", "ИИ остановлен в этом чате на сутки"]


def test_staff_can_turn_the_ai_back_on_at_once(business):
    """They looked: it is a customer with a long order. The count starts again from the stop."""
    llm = Always()
    at = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC) + timedelta(seconds=30)
    assert say(business.id, llm, "ещё", at).reply == HANDED_OVER_REPLY
    with db.new_session() as s:
        conv = s.get(Conversation, conv_of(business.id).id)
        conv.ai_paused_until = None  # «Включить ИИ» in the dialogue
        s.add(conv)
        s.commit()
    assert say(business.id, llm, "продолжим", at + timedelta(minutes=1)).reply == "Ответ 61."
    assert len(stops(business.id)) == 1


def test_a_slow_loop_is_stopped_by_the_day(business):
    """One answer every seven minutes never makes sixty in an hour, and makes two hundred in a day."""
    llm = Always()
    say(business.id, llm, "здравствуйте", NOW_UTC)
    conv = conv_of(business.id)
    with db.new_session() as s:
        for i in range(engine.ANSWERS_PER_DAY - 1):
            s.add(Message(business_id=business.id, conversation_id=conv.id, role="ai", text="ответ", created_at=NOW_UTC + timedelta(minutes=7 * (i + 1))))
        s.commit()
    at = NOW_UTC + timedelta(minutes=7 * engine.ANSWERS_PER_DAY)  # 23 hours 20 minutes on
    out = say(business.id, llm, "ещё", at)
    assert out.reply == HANDED_OVER_REPLY and len(llm.calls) == 1
    assert conv_of(business.id).ai_paused_until == at + timedelta(hours=24)
    assert stops(business.id)[0].summary.startswith("ИИ остановлен в этом чате на сутки: за последние сутки он ответил 200 раз.")


def test_the_owners_own_test_chat_has_no_limit(business):
    llm = Always()
    last = chat(business.id, llm, engine.ANSWERS_PER_HOUR + 5, NOW_UTC, channel=TEST_CHANNEL, chat="test")
    assert len(llm.calls) == 65 and stops(business.id) == [] and last > NOW_UTC


def test_other_chats_of_the_business_are_not_touched(business):
    llm = Always()
    at = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC) + timedelta(seconds=30)
    assert say(business.id, llm, "ещё", at).reply == HANDED_OVER_REPLY
    assert say(business.id, llm, "Сколько стоит чистка?", at, chat="701").reply == "Ответ 61."


def test_a_stop_is_a_request_to_staff_and_nothing_else(business):
    llm = Always()
    at = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC) + timedelta(seconds=30)
    say(business.id, llm, "ещё", at)
    assert "limit" in nudges.KINDS  # staff are reminded if nobody looks
    assert "limit" not in LEAD_KINDS and "limit" not in funnel.KINDS  # not a sale, not for the CRM
    with db.new_session() as s:
        assert faq_gaps.open_gaps(s, s.get(Business, business.id), at + timedelta(minutes=1)) == []  # not a question without an answer


def test_stop_word_at_the_limit_is_still_recorded(business):
    llm = Always()
    at = chat(business.id, llm, engine.ANSWERS_PER_HOUR, NOW_UTC) + timedelta(seconds=30)
    assert say(business.id, llm, "отписаться", at).reply == HANDED_OVER_REPLY
    assert conv_of(business.id).broadcast_opt_out is True
