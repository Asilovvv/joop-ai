"""The line about the end of the trial or paid month in the owner's app in Kyrgyz (joop/period_ky.py): every form
period_end.banner has, said with the same dates and numbers; the people screen's word in Kyrgyz too."""

import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from joop import db, period_ky
from joop.models import Payment
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture
from .test_period_banner import at, trial  # noqa: F401 - the clock fixture

KY = {"Accept-Language": "ky"}
RUSSIAN = re.compile(r"\b(клиентам|отвечает|закончился|заканчивается|осталось|оплаты|остановится|подписка|Заявка|"
                     r"перевода|Напишите|бесплатный|мастера|приходят|отвечайте)\b")


def _line(settings, rt, lang: dict | None = None) -> dict | None:
    with TestClient(create_app(settings, rt, init=False)) as c:
        h = auth(sign_in(c).json()["token"])
        return c.get("/api/mobile/summary", headers={**h, **(lang or {})}).json()["period"]


@pytest.mark.parametrize("state,day", [({}, 14), ({}, 17), ({}, 25), ({"cancelled": True}, 17), ({"free": True}, 14),
                                       ({"suspended": True}, 5), ({"transfer": True}, 25)])
def test_every_form_of_the_line_in_kyrgyz(settings, rt, business, at, state, day):  # noqa: F811
    trial(business.id, **{k: v for k, v in state.items() if k != "transfer"})
    if state.get("transfer"):  # already paid by transfer, waiting for the founder
        with db.new_session() as s:
            s.add(Payment(business_id=business.id, amount_som=1500, created_at=datetime(2026, 11, 24)))
            s.commit()
    at(day)
    ru, ky = _line(settings, rt), _line(settings, rt, KY)
    assert ru is not None and ky is not None
    assert ky["text"] != ru["text"] and not RUSSIAN.search(ky["text"]), ky["text"]
    assert re.findall(r"\d+", ky["text"]) == re.findall(r"\d+", ru["text"])  # the same dates, times, days, masters
    assert {k: ky[k] for k in ("level", "pay_url", "ask_owner")} == {k: ru[k] for k in ("level", "pay_url", "ask_owner")}


def test_the_forms_read_as_they_should():
    assert period_ky.kyrgyz("Пробный период заканчивается 16.11 в 12:00 — осталось 2 дня. Без оплаты ИИ остановится 19.11.") \
        == "Сыноо мезгили 16.11 күнү саат 12:00 бүтөт — 2 күн калды. Төлөм болбосо, ИИ 19.11 күнү токтойт."
    assert period_ky.kyrgyz("ИИ не отвечает клиентам с 19.11: оплаченный период закончился. Сообщения из Telegram и с "
                            "сайта приходят вам — отвечайте в «Диалогах».").startswith(
        "ИИ 19.11 күнү токтоду, кардарларга жооп бербей жатат: төлөнгөн мезгил бүттү.")
    assert period_ky.kyrgyz("Новая форма строки.") == "Новая форма строки."  # unknown: stays Russian


def test_the_people_screen_word_in_kyrgyz(client, business):
    h = auth(sign_in(client).json()["token"])
    assert client.get("/api/mobile/me", headers={**h, **KY}).json()["people_label"] == "Дарыгерлер"
    assert client.get("/api/mobile/staff", headers={**h, **KY}).json()["label"] == "Дарыгерлер"
    assert client.get("/api/mobile/staff", headers=h).json()["label"] == "Врачи"
