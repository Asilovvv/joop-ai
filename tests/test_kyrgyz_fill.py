import json

from sqlmodel import select

from joop import db, kyrgyz
from joop.models import Faq, Service

from .test_web import client, csrf_of, login  # noqa: F401 (client is a fixture)


def test_clean_keeps_kyrgyz_and_drops_bad_suggestions():
    assert kyrgyz.clean("Маникюр", "Маникюр ") == ""  # untranslated copy
    assert kyrgyz.clean("Есть Wi-Fi?", "Wi-Fi барбы?") == "Wi-Fi барбы?"
    assert kyrgyz.clean("Стрижка", "Шаш қию") == ""  # Kazakh letter
    assert kyrgyz.clean("Стрижка", "Chach kyrkuu") == ""  # Latin instead of Cyrillic
    assert kyrgyz.clean("Стрижка", "«Чач кыркуу»") == "Чач кыркуу"
    assert kyrgyz.clean("Стрижка", 5) == ""


def test_suggest_needs_a_list_of_the_same_length(llm):
    llm.write = lambda instruction, text, usage: '```json\n["Чач кыркуу"]\n```'
    assert kyrgyz.suggest(llm, ["Стрижка"]) == ["Чач кыркуу"]
    llm.write = lambda instruction, text, usage: '["Чач кыркуу"]'
    assert kyrgyz.suggest(llm, ["Стрижка", "Маникюр"]) is None
    llm.write = lambda instruction, text, usage: None
    assert kyrgyz.suggest(llm, ["Стрижка"]) is None


def test_panel_button_fills_only_empty_fields(client, business, llm):
    token = login(client)
    with db.new_session() as s:
        s.add(Service(business_id=business.id, name="Отбеливание", price="8 000"))
        s.add(Faq(business_id=business.id, question="Есть Wi-Fi?", answer="Да."))
        s.commit()
        empty = [r.name if isinstance(r, Service) else r.question for r in kyrgyz.empty_fields(s, business)]
        kept = {x.id: x.name_ky for x in s.exec(select(Service).where(Service.business_id == business.id, Service.name_ky != "")).all()}
    seen = {}

    def write(instruction, text, usage):
        seen["items"] = json.loads(text)
        return json.dumps(["Агартуу" if t == "Отбеливание" else ("Wi-Fi барбы?" if t == "Есть Wi-Fi?" else t) for t in seen["items"]],
                          ensure_ascii=False)

    llm.write = write
    page = client.post("/panel/kyrgyz/fill", data={"back": "faq", "csrf": token})
    assert seen["items"] == empty  # only the empty fields were sent
    assert "ИИ заполнил кыргызских вариантов: 2" in page.text
    with db.new_session() as s:
        assert s.exec(select(Service).where(Service.name == "Отбеливание")).one().name_ky == "Агартуу"
        assert s.exec(select(Faq).where(Faq.question == "Есть Wi-Fi?")).one().question_ky == "Wi-Fi барбы?"
        for sid, name_ky in kept.items():
            assert s.get(Service, sid).name_ky == name_ky  # owner's wording untouched
    if len(empty) > 2:
        assert "Не получилось" in page.text  # the other items came back untranslated


def test_panel_button_reports_failure_and_shows_on_pages(client, business, llm):
    token = login(client)
    assert "Заполнить пустые с помощью ИИ" in client.get("/panel/services").text
    assert "Заполнить пустые с помощью ИИ" in client.get("/panel/faq").text
    with db.new_session() as s:
        s.add(Service(business_id=business.id, name="Отбеливание"))
        s.commit()
    llm.write = lambda instruction, text, usage: "не знаю"
    assert "не смог" in client.post("/panel/kyrgyz/fill", data={"back": "services", "csrf": token}).text
