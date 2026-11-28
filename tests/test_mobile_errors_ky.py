"""The app API's refusals in Kyrgyz for an app in Kyrgyz (joop/errors_ky.py), Russian otherwise."""

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from joop import errors_ky, free_plan, reschedule, schedule
from joop.web import accounts
from joop.web.app import create_app

from .test_mobile import auth, client, sign_in  # noqa: F401 - the client fixture

ROOT = Path(__file__).resolve().parent.parent / "joop"
KY = {"Accept-Language": "ky"}


def _fixed_refusals() -> list[str]:
    """Every refusal of the app API written as a plain sentence: `_fail(status, "…")`."""
    tree = ast.parse((ROOT / "web" / "mobile.py").read_text(encoding="utf-8"))
    return [call.args[1].value for call in ast.walk(tree)
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_fail" and len(call.args) == 2
            and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str)]


def test_every_fixed_refusal_of_the_app_api_has_its_kyrgyz():
    fixed = _fixed_refusals()
    assert len(fixed) > 40
    assert [text for text in fixed if text not in errors_ky.KY_ERRORS] == []
    # the helpers' refusals the app API passes on as they are
    for text in (free_plan.TOO_MANY, free_plan.TOO_MANY_EXAMPLE, schedule.ALTEGIO):
        assert text in errors_ky.KY_ERRORS, text
    for text in ("Запись отменена: переносить нечего.", "Это то же самое время."):
        assert text in errors_ky.KY_ERRORS and text in Path(reschedule.__file__).read_text(encoding="utf-8")
    for text in ("Напишите имя сотрудника.", "Такой логин уже есть.", f"Не больше {accounts.MAX_USERS} входов на компанию.",
                 f"Пароль должен быть не короче {accounts.MIN_PASSWORD} символов."):  # accounts.add_login's
        assert errors_ky.kyrgyz(text) != text, text


def test_the_patterns_keep_names_and_numbers():
    assert errors_ky.kyrgyz("«Большой зал» вмещает до 300 гостей.") == "«Большой зал» 300 конокко чейин батат."
    assert errors_ky.kyrgyz("Квитанция №10423 уже есть.") == "№10423 квитанция бар."
    assert errors_ky.kyrgyz("Пароль должен быть не короче 8 символов.") == "Сырсөз кеминде 8 белгиден турушу керек."
    assert errors_ky.kyrgyz("WhatsApp не подключён в разделе «Каналы».") == "WhatsApp «Каналы» бөлүмүндө туташтырылган эмес."
    assert errors_ky.kyrgyz("Что-то новое.") == "Что-то новое."  # unknown: stays Russian


def test_an_app_in_kyrgyz_gets_its_refusals_in_kyrgyz(client, business):
    r = client.post("/api/mobile/login", json={"company": "aktish", "password": "wrong-pass"}, headers=KY)
    assert (r.status_code, r.json()["error"]) == (401, "Логин же сырсөз туура эмес.")
    r = client.post("/api/mobile/login", json={"company": "aktish", "password": "wrong-pass"})
    assert r.json()["error"] == "Неверный логин или пароль."  # no language sent: Russian
    h = auth(sign_in(client).json()["token"])
    r = client.post("/api/mobile/contacts", headers={**h, **KY}, json={"work_start": "18:00", "work_end": "09:00"})
    assert (r.status_code, r.json()["error"]) == (422, "Иш күнүнүн аягы башталышынан кеч болушу керек.")
    r = client.post("/api/mobile/accounts", headers={**h, **KY}, json={"name": "Айгерим", "login": "aigerim", "password": "short"})
    assert r.json()["error"] == "Сырсөз кеминде 8 белгиден турушу керек."  # from accounts.add_login, through _fail
    assert client.post("/api/mobile/accounts", headers=h, json={"name": "Айгерим", "login": "aigerim",
                                                                 "password": "short"}).json()["error"].startswith("Пароль")


def test_the_language_does_not_leak_between_requests(engine, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        for lang, error in [("ky", "Логин же сырсөз туура эмес."), ("ru", "Неверный логин или пароль."),
                            ("ky", "Логин же сырсөз туура эмес."), ("", "Неверный логин или пароль.")]:
            r = c.post("/api/mobile/login", json={"company": "nobody", "password": "x"}, headers={"Accept-Language": lang})
            assert r.json()["error"] == error
