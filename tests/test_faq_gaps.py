"""Questions the AI handed to people become FAQ candidates in the panel."""

from datetime import timedelta

from sqlmodel import select

from joop import db
from joop.faq_gaps import open_gaps
from joop.models import Business, Conversation, Faq, Lead, Message
from joop.timeutil import utcnow

from .test_web import client, csrf_of, login  # noqa: F401  (client is a fixture)


def handoff(s, b, text, at, summary="Уточнить у администратора"):
    conv = Conversation(business_id=b.id, channel="telegram", chat_id=f"c{at.timestamp()}", created_at=at)
    s.add(conv)
    s.flush()
    s.add(Message(business_id=b.id, conversation_id=conv.id, role="customer", text=text, created_at=at))
    lead = Lead(business_id=b.id, conversation_id=conv.id, kind="handoff", summary=summary, created_at=at)
    s.add(lead)
    s.flush()
    return lead


def test_gaps_are_customer_questions_not_yet_in_the_faq(business):
    now = utcnow()
    with db.new_session() as s:
        b = s.get(Business, business.id)
        s.add(Faq(business_id=b.id, question="Есть ли парковка у клиники?", answer="Да."))
        handoff(s, b, "Можно прийти с ребёнком 5 лет?", now - timedelta(days=2))
        handoff(s, b, "Итим менен келсем болобу?", now - timedelta(days=1))
        handoff(s, b, "можно прийти с ребёнком 5 лет", now - timedelta(hours=5))  # the same question again: shown once
        handoff(s, b, "Есть ли парковка у клиники", now - timedelta(hours=4))  # already answered in the FAQ
        handoff(s, b, "2", now - timedelta(hours=3), summary="Низкая оценка 2/5 после визита")  # a rating, not a question
        handoff(s, b, "Делаете ли вы виниры?", now - timedelta(days=40))  # older than 30 days
        s.commit()
        gaps = open_gaps(s, b, now)
    assert [g.text for g in gaps] == ["можно прийти с ребёнком 5 лет", "Итим менен келсем болобу?"]
    assert [g.kyrgyz for g in gaps] == [False, True]
    assert gaps[0].note == "Уточнить у администратора"


def test_owner_answers_a_gap_once_and_it_leaves_the_list(client, business):
    now = utcnow()
    with db.new_session() as s:
        b = s.get(Business, business.id)
        lead = handoff(s, b, "Итим менен келсем болобу? <script>", now - timedelta(hours=1))
        other = Business(slug="other", name="Другой")
        s.add(other)
        s.flush()
        foreign = handoff(s, other, "Чужой вопрос", now)
        s.commit()
        lead_id, foreign_id = lead.id, foreign.id
    token = login(client)
    page = client.get("/panel/faq").text
    assert "Что ИИ передал вам за 30 дней" in page
    block = page.split("Что ИИ передал")[1].split("Добавить вопрос")[0]
    assert "&lt;script&gt;" in block and "<script>" not in block
    assert f'name="lead_id" value="{lead_id}"' in page
    assert 'name="question_ky" value="Итим менен келсем болобу? &lt;script&gt;"' in page  # Kyrgyz goes to the Kyrgyz field
    # The owner rewrites the question in Russian and answers it.
    client.post("/panel/faq", data={"question": "Можно с собакой?", "question_ky": "Ит менен болобу?", "answer": "Нет, с животными нельзя.",
                                    "lead_id": str(lead_id), "csrf": token})
    with db.new_session() as s:
        row = s.exec(select(Faq).where(Faq.question == "Можно с собакой?")).one()
        assert row.source_lead_id == lead_id
        assert open_gaps(s, s.get(Business, business.id), now) == []
    assert "Что ИИ передал вам за 30 дней" not in client.get("/panel/faq").text
    # A lead of another business cannot be attached.
    client.post("/panel/faq", data={"question": "Q", "answer": "A", "lead_id": str(foreign_id), "csrf": csrf_of(client.get("/panel/faq").text)})
    with db.new_session() as s:
        assert s.exec(select(Faq).where(Faq.question == "Q")).one().source_lead_id is None


def test_weekly_report_reminds_the_owner_of_unanswered_questions(business):
    from joop.scheduler import weekly_report_text

    now = utcnow()
    with db.new_session() as s:
        b = s.get(Business, business.id)
        handoff(s, b, "Есть ли у вас детское кресло?", now - timedelta(days=1))
        s.commit()
        text = weekly_report_text(s, b, now)
        assert "у ИИ не было ответа: 1 (панель, раздел «Вопросы»)" in text and "ИИ будет отвечать на них сам" in text
        s.add(Faq(business_id=b.id, question="Есть ли у вас детское кресло?", answer="Да."))
        s.commit()
        assert "не было ответа" not in weekly_report_text(s, b, now)
