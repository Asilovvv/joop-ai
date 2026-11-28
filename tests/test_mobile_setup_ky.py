"""«Запуск» in the owner's app in Kyrgyz: the app sends its language (Accept-Language) and the server says the panel's
launch steps in Kyrgyz (joop/checklist_ky.py), with the same facts; without it the steps stay as the panel's."""

import re

import pytest
from fastapi.testclient import TestClient
from joop import billing, db
from joop.models import Business
from joop.niches import all_packs
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC
from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

KY = {"Accept-Language": "ky"}
# words of the panel's Russian steps that Kyrgyz does not have: none may be left
RUSSIAN = re.compile(r"\b(Осталось|указать|сейчас|из них|пример|Проверьте|Подключите|Получайте|Первый|настоящ\w*|Оплата|"
                     r"Свободные|Впишите|клиент\w*|Напишите|спросите|Табличка|Бесплатный|часы работы|Контакты)\b")


def _no_russian(text: str) -> bool:
    return not RUSSIAN.search(re.sub(r"\([^)]*\)", "", text))  # the example's own values, in brackets, are the owner's data


def _setup(c, slug: str, password: str, lang: dict | None = None) -> dict:
    h = auth(sign_in(c, company=slug, password=password).json()["token"])
    return c.get("/api/mobile/setup", headers={**h, **(lang or {})}).json()


@pytest.mark.parametrize("niche", all_packs())
def test_every_niche_reads_its_launch_in_kyrgyz(engine, settings, rt, niche):
    with db.new_session() as s:
        create_business(s, slug="kg", name="Кыргыз Бизнес", password="kg-pass-2026", niche=niche, demo=True, now_utc=NOW_UTC)
        s.commit()
    with TestClient(create_app(settings, rt, init=False)) as c:
        ru, ky = _setup(c, "kg", "kg-pass-2026"), _setup(c, "kg", "kg-pass-2026", KY)
    assert [x["key"] for x in ky["steps"]] == [x["key"] for x in ru["steps"]]
    assert [x["done"] for x in ky["steps"]] == [x["done"] for x in ru["steps"]]
    for r, k in zip(ru["steps"], ky["steps"]):
        assert k["title"] != r["title"] and _no_russian(k["title"]) and _no_russian(k["hint"]), (k["key"], k["title"], k["hint"])
        assert re.findall(r"\d+", r["title"]) == re.findall(r"\d+", k["title"])  # the same counts
        assert k["panel"] == r["panel"]
    assert _no_russian(ky["online"]["label"])


def test_the_other_branches_in_kyrgyz(client, business):
    """A clinic past the example: contacts written, own people with free times, a bot, the free plan."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.telegram_bot_token, b.telegram_bot_username = "123:abc", "aktish_bot"
        s.add(b)
        billing.start_trial(s, b, 14, NOW_UTC)
        s.flush()
        sub = billing.get_subscription(s, b.id)
        sub.plan = "free"
        s.add(sub)
        s.commit()
    data = _setup(client, "aktish", "secret-pass", KY)
    steps = {x["key"]: x for x in data["steps"]}
    assert "t.me/aktish_bot" in steps["real"]["hint"] and "2ГИСке" in steps["real"]["hint"]
    assert steps["slots"]["title"] == "Жазылуу үчүн бош убакыттар"
    assert steps["pay"]["title"] == "Акысыз тариф: бир чебер, мөөнөтсүз"
    for step in data["steps"]:
        assert _no_russian(step["title"]) and _no_russian(step["hint"]), (step["key"], step["title"], step["hint"])
    ru = _setup(client, "aktish", "secret-pass")
    assert ru["steps"][0]["title"] == "Контакты и часы работы"  # no language sent: the panel's Russian
