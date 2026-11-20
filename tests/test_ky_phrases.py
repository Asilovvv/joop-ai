"""The list of fixed Kyrgyz phrases for a native speaker (joop/ky_phrases.py, /owner/kyrgyz)."""

import csv
import io

from joop import ky_phrases
from joop.__main__ import main

from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)


def test_finds_phrases_customers_see_with_their_russian_twin():
    phrases = ky_phrases.collect()
    by_text = {p.ky: p for p in phrases}
    assert by_text["Жазылдыңыз: {when}, {who}."].ru == "Ваша запись: {when}, {who}."  # BOOKED_KY / BOOKED_RU
    assert by_text["Брондоп койдум."].where.startswith("joop/confirmations.py:")  # no ң/ө/ү: found by its _KY name
    assert any("Telegram аркылуу эскертүү" == p.ky for p in phrases)  # the booking page's "ky" dict
    assert any(p.where.startswith("joop/web/templates/webchat.html:") for p in phrases)  # the site chat's script


def test_leaves_out_what_no_customer_reads():
    phrases = ky_phrases.collect()
    files = {p.where.split(":")[0] for p in phrases}
    assert not {"joop/agent/prompt.py", "joop/kyrgyz.py", "joop/ky_phrases.py"} & files  # model instructions
    assert not any(p.ky in {"ң", "ө", "ү"} or "[а-я" in p.ky for p in phrases)  # letters and regexes
    assert not any("cases.yaml" in p.where for p in phrases)  # test dialogues


def test_csv_for_the_speaker_opens_in_excel(tmp_path):
    out = tmp_path / "ky.csv"
    assert main(["ky-phrases", "--csv", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0] == ["№", "Где в коде", "По-русски", "По-кыргызски", "Верно? (да/нет)", "Как правильно"]
    assert len(rows) - 1 == len(ky_phrases.collect()) > 50


def test_console_page_and_download(engine, app_client):
    assert app_client.get("/owner/kyrgyz", follow_redirects=False).status_code in (303, 302, 401, 403)
    owner_login(app_client)
    page = app_client.get("/owner/kyrgyz").text
    assert "Кыргызские фразы на проверку" in page and "Жазылдыңыз: {when}, {who}." in page
    r = app_client.get("/owner/kyrgyz.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "По-кыргызски" in r.text
