"""The price list and FAQ drafted by the AI from pasted text, kept only where the text supports it (joop/autofill.py)."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import autofill, db
from joop.models import Faq, Service
from joop.web import autofill as page
from joop.web.app import create_app

from .test_web import csrf_of, login

SOURCE = """Салон «Айгерим»
Маникюр с покрытием — 1 200 сом
Педикюр — от 1 500
Наращивание ресниц 2 000 / 2 500 (2 часа)
Брови: коррекция 400
Работаем ежедневно с 9:00 до 21:00, парковка во дворе. Оплата наличными и MBank."""

ANSWER = {
    "services": [
        {"name": "Маникюр с покрытием", "name_ky": "Шеллак менен маникюр", "price": "1 200", "note": ""},
        {"name": "Педикюр", "price": "от 1 500"},
        {"name": "Наращивание ресниц", "price": "2 000–2 500", "note": "2 часа"},
        {"name": "Коррекция бровей", "price": "450"},  # the text says 400
        {"name": "Окрашивание волос", "price": "3 000"},  # not in the text at all
        {"name": "маникюр с покрытием", "price": "1 200"},  # the same item twice
    ],
    "faq": [
        {"question": "Какой график работы?", "answer": "Ежедневно с 9:00 до 21:00."},
        {"question": "Есть ли парковка?", "answer": "Да, во дворе."},
        {"question": "Есть скидки?", "answer": "Скидка 10% по средам."},  # 10 is not in the text
    ],
}


class Writer:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def write(self, instruction, text, usage):
        self.calls.append(text)
        return self.answers.pop(0) if self.answers else None


def test_keeps_only_what_the_text_supports():
    p = autofill.propose(Writer("Вот что нашлось:\n```json\n" + json.dumps(ANSWER, ensure_ascii=False) + "\n```"),
                         SOURCE, ["Педикюр"], ["Есть ли парковка?"])
    names = [s.name for s in p.services]
    assert names == ["Маникюр с покрытием", "Педикюр", "Наращивание ресниц", "Коррекция бровей"]
    first, pedicure, lashes, brows = p.services
    assert first.price == "1 200" and first.name_ky == ""  # a Kyrgyz name the text does not have is not kept
    assert pedicure.duplicate and pedicure.price == "от 1 500"
    assert lashes.price == "2 000–2 500" and lashes.note == "2 часа"
    assert brows.price == "" and brows.price_dropped  # 450 is not in the text: the owner fills it in
    assert [q.question for q in p.faq] == ["Какой график работы?", "Есть ли парковка?"] and p.faq[1].duplicate
    assert p.dropped == 2  # the invented service and the invented discount


def test_numbers_and_retries():
    nums = autofill._source_numbers("Стрижка 500 700, тел. 0555 123 456, 1.500")
    assert {"500", "700", "1500", "0555123456"} <= nums and "1700" not in nums
    w = Writer("не знаю", json.dumps({"services": [{"name": "Стрижка", "price": "500"}], "faq": []}, ensure_ascii=False))
    p = autofill.propose(w, "Стрижка 500", [], [])
    assert len(w.calls) == 2 and p.services[0].price == "500"
    ky = json.dumps({"services": [{"name": "Чистка зубов", "name_ky": "Тиш тазалоо", "price": "2 500"}]}, ensure_ascii=False)
    assert autofill.propose(Writer(ky), "Чистка зубов / Тиш тазалоо — 2 500 сом", [], []).services[0].name_ky == "Тиш тазалоо"
    assert autofill.propose(Writer("нет", "нет"), "Стрижка 500", [], []) is None
    assert autofill.propose(Writer(), "  ", [], []) is None
    long = autofill.propose(w := Writer(json.dumps({"services": [], "faq": []})), "х" * 9000, [], [])
    assert long.empty and len(w.calls[0]) == autofill.MAX_SOURCE


@pytest.fixture
def web(settings, rt, business):
    page.reset_limits()
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c
    page.reset_limits()


def test_panel_preview_then_save_only_ticked_rows(web, business, rt):
    rt._llm = Writer(json.dumps(ANSWER, ensure_ascii=False))
    token = login(web)
    assert "Заполнить из текста" in web.get("/panel/services").text and "Заполнить из текста" in web.get("/panel/faq").text
    html = web.post("/panel/autofill", data={"csrf": token, "source": SOURCE, "back": "services"}).text
    assert "Проверьте, что нашёл ИИ" in html and "убрал 2 строки, которых в тексте нет" in html and "цены нет в тексте" in html
    with db.new_session() as s:
        before = len(s.exec(select(Service).where(Service.business_id == business.id)).all())
    form = {"csrf": csrf_of(html), "back": "services",
            "s0_on": "1", "s0_name": "Маникюр с покрытием", "s0_price": "1 200",
            "s3_on": "1", "s3_name": "Коррекция бровей", "s3_price": "400",  # the owner filled the price in
            "s2_name": "Наращивание ресниц", "s2_price": "2 000–2 500",  # unticked: not added
            "f0_on": "1", "f0_q": "Какой график работы?", "f0_a": "Ежедневно с 9:00 до 21:00."}
    r = web.post("/panel/autofill/save", data=form)
    assert "Добавлено: услуг 2, вопросов 1." in r.text
    with db.new_session() as s:
        services = s.exec(select(Service).where(Service.business_id == business.id)).all()
        assert len(services) == before + 2
        brows = next(x for x in services if x.name == "Коррекция бровей")
        assert (brows.price, brows.price_value) == ("400", 400)
        assert s.exec(select(Faq).where(Faq.question == "Какой график работы?")).one().answer == "Ежедневно с 9:00 до 21:00."
    assert "Добавлено: услуг 0" not in web.post("/panel/autofill/save", data=form).text  # a second press adds no duplicates


def test_panel_failures_and_daily_limit(web, rt, monkeypatch):
    token = login(web)
    rt._llm = Writer()
    assert "ИИ сейчас не смог разобрать текст" in web.post("/panel/autofill", data={"csrf": token, "source": "Стрижка 500"}).text
    rt._llm = Writer(json.dumps({"services": [], "faq": []}))
    assert "не нашлось услуг" in web.post("/panel/autofill", data={"csrf": token, "source": "Привет"}).text
    assert "Вставьте текст" in web.post("/panel/autofill", data={"csrf": token, "source": " "}).text
    monkeypatch.setattr(page, "PER_DAY", 2)
    assert "до 2 раз в сутки" in web.post("/panel/autofill", data={"csrf": token, "source": "Стрижка 500", "back": "faq"}).text
