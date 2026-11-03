"""The AI says it is an AI at first contact; the owner reviews the first week's dialogues (joop/trust.py)."""

from datetime import timedelta

from joop import db, trust
from joop.agent.engine import DEFAULT_GREETING, handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Conversation, Message
from joop.scheduler import run_due_jobs

from .conftest import NOW_UTC, FakeLLM

MORNING = NOW_UTC + timedelta(hours=9)  # 08:14 next day in Bishkek: the digest hour


def say(business_id, rt, text, channel="whatsapp", chat="996555000111", now=NOW_UTC):
    with db.new_session() as s:
        out = handle_incoming(s, s.get(Business, business_id), IncomingMessage(channel, chat, "text", text, "", f"{channel}:{chat}:{text[:9]}"),
                              rt.get_llm, now)
        s.commit()
        return out


def test_first_whatsapp_reply_discloses_once_without_a_double_greeting(business, rt):
    rt._llm = FakeLLM([AgentReply("Здравствуйте! Консультация — 500 сом."), AgentReply("Да, завтра есть 10:00.")])
    first = say(business.id, rt, "Сколько стоит консультация?")
    assert first.reply == ("Здравствуйте! Я ИИ-помощник «Ак-Тиш Дент»: отвечаю сразу, а если нужно — позову администратора."
                           "\n\nКонсультация — 500 сом.")
    assert say(business.id, rt, "А завтра можно?").reply == "Да, завтра есть 10:00."  # only once
    rt._llm = FakeLLM([AgentReply("Саламатсызбы! Консультация 500 сом.")])
    ky = say(business.id, rt, "Саламатсызбы, консультация канча турат?", chat="996555000222")
    assert ky.reply.startswith("Саламатсызбы! Мен «Ак-Тиш Дент» ИИ-жардамчысымын") and ky.reply.endswith("\n\nКонсультация 500 сом.")


def test_telegram_and_web_rely_on_the_greeting_and_the_header(business, rt):
    rt._llm = FakeLLM([AgentReply("Чем помочь?"), AgentReply("Чем помочь?")])
    assert say(business.id, rt, "Привет", channel="telegram", chat="42").reply == "Чем помочь?"
    assert "ИИ-помощник" in DEFAULT_GREETING  # /start says it instead
    assert say(business.id, rt, "Привет", channel="web", chat="web-abc").reply == "Чем помочь?"


def test_week_one_review_in_the_morning_summary(business, rt):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.admin_chat_ids, b.digest_hour = "999", 8
        s.add(b)
        s.commit()
    with db.new_session() as s:
        assert trust.week_one_review(s, s.get(Business, business.id), NOW_UTC) is None  # no real customers yet
    rt._llm = FakeLLM([AgentReply("Консультация — 500 сом.")] * 5)
    for i in range(4):
        say(business.id, rt, f"Сколько стоит консультация? {i}", chat=f"99655500011{i}", now=NOW_UTC - timedelta(hours=i))
    say(business.id, rt, "test", channel="console", chat="panel-1")  # the panel's test chat does not count
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), MORNING)
        s.commit()
    assert report["digest"] is True
    [text] = [t for chat, t in rt.tg.sent if chat == "999" and t.startswith("Первая неделя с ИИ, день 1.")]
    assert text.count("\n   ИИ: «") == 3 and "https://joop.test/panel/conversations/" in text  # three of four, with links
    assert "впишите правильный в «Вопросы»" in text
    with db.new_session() as s:  # day 9: the week is over
        assert trust.week_one_review(s, s.get(Business, business.id), NOW_UTC + timedelta(days=9)) is None
