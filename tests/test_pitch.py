"""A demo on the prospect's own price list, with a screenshot-ready dialogue (joop/pitch.py)."""

import json

from sqlmodel import select

from joop import db
from joop.agent.llm import AgentReply
from joop.models import Business, Faq, Prospect, Service, Slot

from .conftest import FakeLLM
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)

SOURCE = """Салон «Айгерим»
Маникюр с покрытием — 1 200 сом
Педикюр — от 1 500
Стрижка женская 800
Работаем ежедневно с 9:00 до 21:00, парковка во дворе."""
FOUND = {"services": [{"name": "Маникюр с покрытием", "price": "1 200"}, {"name": "Педикюр", "price": "от 1 500"},
                      {"name": "Стрижка женская", "price": "800"}, {"name": "Окрашивание", "price": "3 000"}],
         "faq": [{"question": "Какой график работы?", "answer": "Ежедневно с 9:00 до 21:00."}]}


def test_pitch_builds_the_demo_from_the_text_and_shows_the_dialogue(app_client, rt):  # noqa: F811
    token = owner_login(app_client)
    app_client.post("/owner/prospects", data={"name": "Салон «Айгерим»", "niche": "beauty", "instagram": "aigerim.kg", "csrf": token})
    with db.new_session() as s:
        pid = s.exec(select(Prospect.id)).one()
    llm = FakeLLM([AgentReply("Маникюр с покрытием — 1 200 сом. Записать вас?"),
                   AgentReply("Завтра есть 18:00 и 19:00. Какое время удобнее?")])
    llm.write = lambda instruction, text, usage: json.dumps(FOUND, ensure_ascii=False)
    rt._llm = llm
    r = app_client.post(f"/owner/prospects/{pid}", data={"action": "pitch", "source": SOURCE, "csrf": token}, follow_redirects=False)
    assert r.headers["location"] == f"/owner/prospects/{pid}/pitch"
    with db.new_session() as s:
        p = s.get(Prospect, pid)
        b = s.get(Business, p.demo_business_id)
        names = [x.name for x in s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.sort)).all()]
        assert names == ["Маникюр с покрытием", "Педикюр", "Стрижка женская"]  # 3 000 is not in the text: dropped
        assert s.exec(select(Faq).where(Faq.business_id == b.id)).one().answer == "Ежедневно с 9:00 до 21:00."
        assert len(s.exec(select(Slot).where(Slot.business_id == b.id)).all()) > 20 and p.status == "demo"
        assert b.name == "Салон «Айгерим»" and b.slug.startswith("demo-")
    assert llm.calls[0]["messages"][-1]["content"] == "Здравствуйте! Сколько стоит маникюр с покрытием?"
    page = app_client.get(f"/owner/prospects/{pid}/pitch").text
    assert 'class="msg customer"' in page and "Маникюр с покрытием — 1 200 сом. Записать вас?" in page
    assert "Завтра есть 18:00 и 19:00" in page and "Взял ваш прайс из поста" in page and "@aigerim.kg" in page
    assert "Демо на прайсе: Салон «Айгерим»" in page
    # the prospects page now links to the dialogue; a second run refills the same demo company
    assert f"/owner/prospects/{pid}/pitch" in app_client.get("/owner/prospects").text
    rt._llm = FakeLLM([AgentReply("Ок."), AgentReply("Ок.")])
    rt._llm.write = llm.write
    app_client.post(f"/owner/prospects/{pid}", data={"action": "pitch", "source": SOURCE, "csrf": token})
    with db.new_session() as s:
        assert len(s.exec(select(Business).where(Business.name == "Салон «Айгерим»")).all()) == 1
        assert len(s.exec(select(Service).where(Service.business_id == p.demo_business_id)).all()) == 3


def test_pitch_without_prices_or_model_explains(app_client, rt):  # noqa: F811
    token = owner_login(app_client)
    app_client.post("/owner/prospects", data={"name": "Кафе", "niche": "restaurant", "csrf": token})
    with db.new_session() as s:
        pid = s.exec(select(Prospect.id)).one()
    assert "Вставьте прайс" in app_client.post(f"/owner/prospects/{pid}", data={"action": "pitch", "source": " ", "csrf": token}).text
    llm = FakeLLM([]); llm.write = lambda *a: json.dumps({"services": [], "faq": []})
    rt._llm = llm
    assert "не нашлось услуг с ценами" in app_client.post(f"/owner/prospects/{pid}", data={"action": "pitch", "source": "Привет", "csrf": token}).text
    llm.write = lambda *a: None
    assert "ИИ не смог разобрать" in app_client.post(f"/owner/prospects/{pid}", data={"action": "pitch", "source": "Кофе 150", "csrf": token}).text
    with db.new_session() as s:
        assert s.get(Prospect, pid).demo_business_id is None  # nothing half-made
    assert app_client.get(f"/owner/prospects/{pid}/pitch").status_code == 404
