import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, placement
from joop.agent.engine import handle_incoming
from joop.channels.base import IncomingMessage
from joop.models import Booking, Business, Conversation, Lead, Message, PlacementAttempt, PlacementQuestion, PlacementTest
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_web import csrf_of


@pytest.fixture
def school(engine):
    with db.new_session() as s:
        b = create_business(s, slug="bsc", name="Языковая школа", password="school-pass", niche="education", demo=True,
                            now_utc=NOW_UTC)
        b.telegram_bot_token = "123:TEST"
        b.admin_chat_ids = "900"
        s.add(b)
        s.commit()
        return b


@pytest.fixture
def client(settings, rt, school):
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c


def login(client, slug="bsc", password="school-pass"):
    token = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"slug": slug, "password": password, "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == "/panel"
    return csrf_of(client.get("/panel").text)


def chat(llm, business_id, text, ext, base_url="https://joop.test"):
    with db.new_session() as s:
        b = s.get(Business, business_id)
        out = handle_incoming(s, b, IncomingMessage("telegram", "4242", "text", text, "Студент", ext), lambda: llm, NOW_UTC,
                              base_url=base_url)
        s.commit()
    return out, llm.calls[-1]["system"]


def test_parse_questions_accepts_numbers_letters_and_text():
    text = ("Раздел;Вопрос;Вариант 1;Вариант 2;Вариант 3;Правильный\n"
            "Грамматика;She ___ a teacher.;am;is;are;2\n"
            "Лексика;Cheap — opposite;expensive;easy;;A\n"
            "Лексика;Go — past;goed;went;gone;Б\n"
            "Чтение;Main idea?;Food;Travel;;Travel\n"
            "Ошибка;Only one option;yes;1\n"
            "Ошибка;Bad answer;a;b;c;7\n")
    questions, errors = placement.parse_questions(text)
    assert [q["correct"] for q in questions] == [1, 0, 1, 1]
    assert questions[1]["options"] == ["expensive", "easy"]
    assert len(errors) == 2 and "Строка 6" in errors[0] and "Строка 7" in errors[1]


def test_scale_and_level():
    bands, errors = placement.parse_scale("0-10 A1\n11–20 A2\nабв\n21-5 B1")
    assert bands == [(0, 10, "A1"), (11, 20, "A2")] and len(errors) == 2
    assert placement.level_for("0-10 A1\n11-20 A2", 15) == "A2"
    assert placement.level_for("0-10 A1", 30) == ""


def test_hint_only_for_schools_with_a_base_url(school, business, llm):
    _, system = chat(llm, school.id, "Какой у меня уровень?", "e1", base_url="")
    assert "/t/" not in system
    _, system = chat(llm, business.id, "Какой у меня уровень?", "e2")  # a dental clinic
    assert "/t/" not in system and "Тест на уровень" not in system


def test_chat_link_test_result_back_to_chat(client, rt, llm, school):
    _, system = chat(llm, school.id, "Хочу узнать свой уровень английского", "e1")
    token = re.search(r"https://joop\.test/t/([0-9a-f]{16})", system).group(1)
    assert "не определяй и не угадывай" in system
    # The same chat keeps one personal link.
    _, again = chat(llm, school.id, "А сколько вопросов?", "e2")
    assert token in again

    page = client.get(f"/t/{token}")
    assert "Начать тест" in page.text and "Согласен" in page.text
    csrf = csrf_of(page.text)
    r = client.post(f"/t/{token}/start", data={"name": "Айгуль", "phone": "0555 123 456", "csrf": csrf})
    assert "согласие" in r.text  # consent is required
    client.post(f"/t/{token}/start", data={"name": "Айгуль", "phone": "0555 123 456", "consent": "1", "csrf": csrf})
    take = client.get(f"/t/{token}")
    assert "Завершить тест" in take.text
    with db.new_session() as s:
        questions = s.exec(select(PlacementQuestion).where(PlacementQuestion.business_id == school.id)).all()
    answers = {f"q{q.id}": str(q.correct) for q in questions}
    answers[f"q{questions[0].id}"] = str((questions[0].correct + 1) % 3)  # one wrong answer
    result = client.post(f"/t/{token}", data={**answers, "csrf": csrf_of(take.text)})
    assert "7 из 8" in result.text and "B2" in result.text

    # Result in the customer's chat, a note for the school, a lead in the panel.
    assert ("4242", rt.tg.sent[0][1]) == rt.tg.sent[0] and "7 из 8" in rt.tg.sent[0][1] and "B2" in rt.tg.sent[0][1]
    assert any(chat_id == "900" and "Айгуль" in text for chat_id, text in rt.tg.sent)
    with db.new_session() as s:
        a = s.exec(select(PlacementAttempt).where(PlacementAttempt.token == token)).one()
        assert a.status == "finished" and a.result_sent and a.level == "B2" and not a.late
        assert s.exec(select(Lead).where(Lead.business_id == school.id, Lead.kind == "lead")).one().customer_name == "Айгуль"
        conv = s.get(Conversation, a.conversation_id)
        assert conv.customer_name == "Айгуль" and conv.customer_phone == "0555 123 456"
        assert s.exec(select(Message).where(Message.conversation_id == conv.id, Message.role == "ai")).all()[-1].text.startswith("Результат теста")

    # A second submit does not re-grade or send again.
    sent = len(rt.tg.sent)
    client.post(f"/t/{token}", data={**{k: "0" for k in answers}, "csrf": csrf_of(take.text)})
    with db.new_session() as s:
        assert s.exec(select(PlacementAttempt).where(PlacementAttempt.token == token)).one().score == 7
    assert len(rt.tg.sent) == sent

    # Next message: the AI knows the level and the chat gets a new link only for a retake.
    _, system = chat(llm, school.id, "Запишите в группу", "e3")
    assert "уже прошёл тест" in system and "уровень B2" in system and token not in system


def test_kyrgyz_chat_gets_kyrgyz_result():
    t = PlacementTest(business_id=1, code="x", title="Англис тили", scale_text="0-5 A1")
    a = PlacementAttempt(business_id=1, test_id=1, token="t", score=4, max_score=5, level="A1", sections_json='{"Грамматика": [2, 3], "Лексика": [2, 2]}')
    text = placement.result_text(t, a, kyrgyz=True)
    assert "5 суроодон 4 туура" in text and "деңгээлиңиз — A1" in text and "Грамматика 2/3" in text


def test_public_link_without_chat(client, rt, school):
    with db.new_session() as s:
        t = s.exec(select(PlacementTest).where(PlacementTest.business_id == school.id)).one()
        t.minutes = 1
        s.add(t)
        s.commit()
        code = t.code
    page = client.get(f"/test/{code}")
    assert "8 вопросов" in page.text
    r = client.post(f"/test/{code}", data={"name": "Бакыт", "phone": "0700 111 222", "consent": "1", "csrf": csrf_of(page.text)})
    token = re.search(r'action="/t/([0-9a-f]{16})"', r.text).group(1)
    with db.new_session() as s:  # submitted long after the time limit
        a = s.exec(select(PlacementAttempt).where(PlacementAttempt.token == token)).one()
        a.started_at -= timedelta(minutes=10)
        s.add(a)
        s.commit()
    result = client.post(f"/t/{token}", data={"csrf": csrf_of(r.text)})
    assert "0 из 8" in result.text and "свяжемся" in result.text
    with db.new_session() as s:
        a = s.exec(select(PlacementAttempt).where(PlacementAttempt.token == token)).one()
        assert a.late and a.level == "A1" and a.conversation_id is None
    assert [c for c, _ in rt.tg.sent] == ["900"]  # only the school is told
    assert client.get("/test/nope").status_code == 404


def test_panel_upload_scale_and_report(client, school):
    token = login(client)
    page = client.get("/panel/tests")
    assert "Тест на уровень" in page.text and "Английский: тест на уровень (демо)" in page.text
    with db.new_session() as s:
        tid = s.exec(select(PlacementTest).where(PlacementTest.business_id == school.id)).one().id
    r = client.post(f"/panel/tests/{tid}/questions", data={"csv": "Грамматика;I ___ happy.;am;is;1\nЛексика;Big;large;small;large", "csrf": token})
    assert "Загружено вопросов: 2" in r.text
    r = client.post(f"/panel/tests/{tid}", data={"title": "Английский", "scale_text": "0-1 A1\nплохо", "minutes": "15", "active": "1", "csrf": token})
    assert "нужен вид" in r.text
    client.post(f"/panel/tests/{tid}", data={"title": "Английский", "scale_text": "0-1 A1\n2-2 A2", "minutes": "15", "active": "1", "csrf": token})
    with db.new_session() as s:
        t = s.get(PlacementTest, tid)
        assert t.scale_text == "0-1 A1\n2-2 A2" and t.minutes == 15 and len(placement.questions_of(s, tid)) == 2
        # A finished test followed by a booking with the same phone counts as a conversion.
        done = NOW_UTC - timedelta(hours=1)
        s.add(PlacementAttempt(business_id=school.id, test_id=tid, token="a" * 16, status="finished", phone="+996 555 123 456",
                               score=2, max_score=2, level="A2", finished_at=done))
        s.add(PlacementAttempt(business_id=school.id, test_id=tid, token="b" * 16, status="finished", phone="0700 000 000",
                               score=0, max_score=2, level="A1", finished_at=done))
        s.add(Booking(business_id=school.id, start=NOW_UTC, customer_phone="0555123456", created_at=NOW_UTC))
        s.commit()
        st = placement.stats(s, school.id)[0]
        assert (st.finished, st.booked, st.conversion) == (2, 1, 50)
    assert "50%" in client.get("/panel/tests").text


def test_tests_section_only_for_schools(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c, "aktish", "secret-pass")
        assert "/panel/tests" not in c.get("/panel").text
        assert c.get("/panel/tests").status_code == 404
