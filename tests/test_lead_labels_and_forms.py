"""Words staff read: a lead named by its niche, numbers with the right ending, phones with spaces.

A removal company's lead read «Заявка на подбор / консультацию», the dashboard said «4 диалогов с клиентами»,
«1 записей сделал ИИ», and phones were one run of digits: «+996777444555».
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.lang import plural
from joop.models import Business, Lead
from joop.niches import all_packs, get_pack
from joop.phone import display_phone
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import login

LEAD_NICHES = sorted(n for n in all_packs() if get_pack(n).has("lead"))


def test_every_lead_niche_names_its_leads():
    labels = {n: get_pack(n).lead_label for n in LEAD_NICHES}
    assert all(label.startswith("Заявка ") for label in labels.values()), labels
    assert len(set(labels.values())) == len(labels)  # each niche its own
    assert labels["cargo"] == "Заявка на перевозку" and labels["education"] == "Заявка на обучение"


@pytest.mark.parametrize("niche", ["cargo", "education", "realty"])
def test_a_qualified_lead_reads_as_the_niche_says(niche, engine):
    with db.new_session() as s:
        b = create_business(s, slug=niche, name="Фирма", password="pass-12345", niche=niche, demo=False, now_utc=NOW_UTC)
        s.commit()
        bid = b.id
    llm = FakeLLM([AgentReply("Передал менеджеру.", lead={"name": "Марат", "phone": "0555 909 808", "details": "Бишкек → Ош"})])
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, bid), IncomingMessage("telegram", "g1", "text", "Нужно. Марат, 0555 909 808",
                                                                 "Марат", "g1-1"), lambda: llm, NOW_UTC)
        s.commit()
        lead = s.exec(select(Lead).where(Lead.business_id == bid)).one()
    assert lead.summary == f"{get_pack(niche).lead_label}. Свяжитесь с клиентом."
    assert "подбор / консультацию" not in lead.summary


def test_russian_forms_after_a_number():
    forms = [plural(n, "диалог", "диалога", "диалогов") for n in (0, 1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101, 111, 112, 122)]
    assert forms == ["диалогов", "диалог", "диалога", "диалога", "диалогов", "диалогов", "диалогов", "диалогов", "диалог",
                     "диалога", "диалогов", "диалог", "диалогов", "диалогов", "диалога"]


def test_phones_read_with_spaces():
    assert display_phone("+996777444555") == "+996 777 444 555"
    assert display_phone("+77011234567") == "+7 701 123 45 67"
    assert display_phone("+996 555 000 001") == "+996 555 000 001" and display_phone(None) == ""
    assert display_phone("+4915112345678") == "+4915112345678"


def _chat(business_id: int, chat_id: str):
    llm = FakeLLM([AgentReply("Здравствуйте!")])
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business_id), IncomingMessage("telegram", chat_id, "text", "Здравствуйте",
                                                                         "Айгуль", f"{chat_id}-1"), lambda: llm, NOW_UTC)
        s.commit()


def test_the_dashboard_figures_agree_with_their_numbers(business, settings, rt):
    """Real chats in the last 14 days: the word under the number follows it."""
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        _chat(business.id, "c1")
        page = re.sub(r"\s+", " ", c.get("/panel").text)
        assert "<b>1</b><span>диалог с клиентами</span>" in page
        for chat in ("c2", "c3", "c4"):
            _chat(business.id, chat)
        page = re.sub(r"\s+", " ", c.get("/panel").text)
        assert "<b>4</b><span>диалога с клиентами</span>" in page and "диалогов с клиентами" not in page
        assert "<b>0</b><span>записей сделал ИИ</span>" in page


def test_the_leads_page_shows_phones_with_spaces(business, settings, rt):
    llm = FakeLLM([AgentReply("Передал администратору.", handoff="Спрашивает про скидку")])
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "c9", "text",
                        "Есть скидка? Мой номер 0777 444 555", "Нурлан", "c9-1"), lambda: llm, NOW_UTC)
        lead = s.exec(select(Lead).where(Lead.business_id == business.id)).one()
        lead.customer_phone = "+996777444555"
        s.add(lead)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/leads").text
    assert "+996 777 444 555" in page and "+996777444555" not in page
