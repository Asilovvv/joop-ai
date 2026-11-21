"""The list of fixed Kyrgyz phrases for a native speaker (joop/ky_phrases.py, /owner/kyrgyz)."""

import csv
import io
import textwrap

import pytest

from joop import ky_phrases
from joop.__main__ import main

from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)


@pytest.fixture(scope="module")
def phrases():
    return ky_phrases.collect()


def _by_text(phrases):
    return {p.ky: p for p in phrases}


def test_finds_phrases_customers_see_with_their_russian_twin(phrases):
    by_text = _by_text(phrases)
    assert by_text["Жазылдыңыз: {when}, {who}."].ru == "Ваша запись: {when}, {who}."  # BOOKED_KY / BOOKED_RU
    assert by_text["Брондоп койдум."].where.startswith("joop/confirmations.py:")  # no ң/ө/ү: found by its _KY name
    assert by_text["Telegram аркылуу эскертүү"].ru == "Напомнить в Telegram"  # the booking page's "ky" table
    assert any(p.where.startswith("joop/web/templates/webchat.html:") for p in phrases)  # the site chat's script


def test_finds_kyrgyz_without_kyrgyz_letters(phrases):
    """Review of #265: most Kyrgyz sentences have no ң, ө or ү, and the first list missed them."""
    by_text = _by_text(phrases)
    # the reply to every model failure: a Kyrgyz line and a Russian line in one text, each to its column
    failure = by_text["Кечиресиз, азыр жооп бере албай жатам. Администратор жакында жооп берет."]
    assert failure.where.startswith("joop/agent/engine.py:") and failure.ru.startswith("Извините, сейчас не получается ответить.")
    # the Kyrgyz branch of `if kyrgyz:` with the Russian text that follows it
    assert by_text["Макул, жазылуу ошол бойдон калат."].ru == "Хорошо, запись остаётся как есть."
    greeting = next(p for p in phrases if p.where.startswith("joop/trust.py:"))
    assert greeting.ky.startswith("Саламатсызбы! Мен «{business.name}» ИИ-жардамчысымын") and greeting.ru.startswith("Здравствуйте! Я ИИ-помощник")
    assert by_text["«{item.name}» кайра сатыкта бар, баасы {item.price}. Калтырып коёлубу?"].ru.startswith("«{item.name}» снова в наличии")
    # a table of texts under "ky": every entry, paired with the "ru" table by its key
    page = {p.ky: p.ru for p in phrases if p.where.startswith("joop/web/booking_page.py:")}
    assert page["Онлайн жазылуу"] == "Запись онлайн" and page["Убакыт"] == "Время" and page["Кызмат"] == "Услуга"
    assert page["Тандалган жок — жеринде тактайбыз"] == "Не выбрана — уточним на месте"
    menu = {p.ky: p.ru for p in phrases if p.where.startswith("joop/web/menu.py:")}
    assert menu["Буйрутма берүү"] == "Заказать" and menu["Азыр жок"] == "Сейчас нет" and menu["Дарек"] == "Адрес"
    assert len(phrases) > 150 and sum(1 for p in phrases if p.ru) > 130


def test_leaves_out_what_no_customer_reads(phrases):
    files = {p.where.split(":")[0] for p in phrases}
    assert not {"joop/agent/prompt.py", "joop/kyrgyz.py", "joop/ky_phrases.py", "joop/lang.py"} & files  # for the model
    assert not any(p.ky in {"ң", "ө", "ү"} or "[а-я" in p.ky for p in phrases)  # letters and regexes
    assert not any("cases.yaml" in p.where for p in phrases)  # test dialogues
    texts = " | ".join(p.ky for p in phrases)
    assert "өзү алып кетет" not in texts and "самовывоз" not in texts  # words the code looks for in a message
    assert "записаться, запиши" not in texts and "подскажите" not in texts  # Russian keyword lists with a Kyrgyz word
    assert "мастер Нургүл" not in texts  # a Russian line with a Kyrgyz name
    assert not any(p.ky == p.ru and len(p.ky.split()) > 3 for p in phrases)  # no Russian sentence in the Kyrgyz column


def test_sections_tell_the_speaker_where_the_phrase_lives(phrases):
    sections = {p.ky: p.section for p in phrases}
    assert sections["Онлайн жазылуу"] in {"Страница записи без переписки", "Онлайн-страница: меню и прайс"}
    assert sections["Жазылдыңыз: {when}, {who}."] == "Подтверждение записи и напоминание"
    assert sections["Жөнөтүү"] == "Чат на сайте"
    assert [p.section for p in phrases] == sorted((p.section for p in phrases), key=[p.section for p in phrases].index)


# --- each rule on a small package of its own ----------------------------------------------------------------------

MODULE = '''
"""A docstring that says «жазып койдум» and «кабыл алынды» is not a phrase."""
import re

DONE_RU, DONE_KY = "Записала вас.", "Жазып койдум."
FOOTER = "Ответьте «стоп»."
FOOTER_KY = "«стоп» деп жазыңыз."
DAYS_KY = ("дүй", "шейш", "шарш")
LINES_KY = ["Биринчи сап ушул жерде турат.", "Экинчи сап ушул жерде турат."]
TEXT = {"ru": {"title": "Запись", "errors": {"taken": "Время занято."}},
        "ky": {"title": "Жазылуу", "errors": {"taken": "Убакыт бош эмес."}}}
BOTH = ("Кечиресиз, азыр жооп бере албай жатам.\\n"
        "Извините, сейчас не получается ответить.")
_MODES = {"жеткирүү": "delivery", "өзү алып кетет": "pickup"}
YES = {"ооба", "макул", "кошуңуз", "ооба кошуңуз"}
WORDS = "цена, сколько, записаться, канча, баасы"
_RX = re.compile(r"[а-яёңөү]{3,} сиз жок")


def notice(name, kyrgyz):
    if kyrgyz:
        return f"«{name}» кайра сатыкта бар."
    return f"«{name}» снова в наличии."


def thanks(lang):
    return "Рахмат!" if lang == "ky" else "Спасибо!"


def note():
    return "ИИ предлагает: окно 16:30, мастер Нургүл"


def sweep():
    return "Суроолорду ушул жерден берсеңиз болот."
'''

TEMPLATE = '''
<section class="card ky-fill"><p>Кыргызские варианты для прайса</p></section>
<p class="sub ky">Суроо бериңиз — дароо жооп беребиз</p>
<span>{{ 'ночью' if c.lang == 'ru' else 'түнкүсүн' }}</span>
<textarea placeholder="Саламатсызбы! Ушул жумада арзандатуу бар."></textarea>
<script>
const T = {
  ru: {send: 'Отправить', off: 'Нет связи.'},
  ky: {send: 'Жөнөтүү', off: 'Байланыш жок.'},
};
</script>
'''


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "pkg"
    (root / "web" / "templates").mkdir(parents=True)
    (root / "texts.py").write_text(textwrap.dedent(MODULE), encoding="utf-8")
    (root / "prompt.py").write_text('RULE = "По-кыргызски так: «Жазуу үчүн телефон номериңизди жазыңызчы»."\n', encoding="utf-8")
    (root / "web" / "templates" / "page.html").write_text(TEMPLATE, encoding="utf-8")
    return {p.ky: p for p in ky_phrases.collect(root)}


def test_rules_in_python(package):
    assert package["Жазып койдум."].ru == "Записала вас."  # A_RU, A_KY = "…", "…"
    assert package["«стоп» деп жазыңыз."].ru == "Ответьте «стоп»."  # FOOTER_KY beside FOOTER
    assert "дүй · шейш · шарш" in package  # a word list is one line
    assert {"Биринчи сап ушул жерде турат.", "Экинчи сап ушул жерде турат."} <= set(package)  # sentences: one each
    assert package["Жазылуу"].ru == "Запись" and package["Убакыт бош эмес."].ru == "Время занято."  # "ky" at any depth
    assert package["Кечиресиз, азыр жооп бере албай жатам."].ru == "Извините, сейчас не получается ответить."
    assert package["«{name}» кайра сатыкта бар."].ru == "«{name}» снова в наличии."  # if kyrgyz: return … / return …
    assert package["Рахмат!"].ru == "Спасибо!"  # x if lang == "ky" else y
    assert "Суроолорду ушул жерден берсеңиз болот." in package  # nothing says it is Kyrgyz but its words
    assert package["Жазып койдум."].where == "pkg/texts.py:5"


def test_rules_leave_out(package):
    texts = " | ".join(package)
    for absent in ("жеткирүү", "өзү алып кетет",  # keys of a lookup table
                   "ооба кошуңуз",  # one of the ways to say yes
                   "цена, сколько",  # Russian keywords with two Kyrgyz ones
                   "сиз жок",  # a regular expression
                   "Нургүл",  # a Russian line with a Kyrgyz name
                   "кабыл алынды",  # a docstring
                   "телефон номериңизди"):  # an instruction to the model (prompt.py)
        assert absent not in texts, absent


def test_rules_in_templates(package):
    assert package["Жөнөтүү"].ru == "Отправить" and package["Байланыш жок."].ru == "Нет связи."  # the script's table
    assert "Суроо бериңиз — дароо жооп беребиз" in package  # class="… ky"
    assert "Кыргызские варианты для прайса" not in package  # class="card ky-fill" is not class "ky"
    assert package["түнкүсүн"].ru == "ночью"  # {{ 'ru' if lang == 'ru' else 'ky' }}
    assert "Саламатсызбы! Ушул жумада арзандатуу бар." in package  # a placeholder
    assert package["Жөнөтүү"].where == "pkg/web/templates/page.html:9"


def test_the_same_text_twice_in_a_file_is_one_row(phrases):
    again = [p for p in phrases if "," in p.where]
    assert again and all(len(set(p.where.split(":")[1].split(","))) > 1 for p in again)
    assert len({(p.where.split(":")[0], p.ky, p.ru) for p in phrases}) == len(phrases)


# --- the table and the page ----------------------------------------------------------------------------------------


def test_csv_for_the_speaker_opens_in_excel(tmp_path, phrases):
    out = tmp_path / "ky.csv"
    assert main(["ky-phrases", "--csv", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0] == ["№", "Раздел", "По-русски", "По-кыргызски", "Верно? (да/нет)", "Как правильно", "Где в коде"]
    assert len(rows) - 1 == len(phrases)
    assert all(len(row) == 7 and row[3] and row[4] == row[5] == "" for row in rows[1:])


def test_console_page_and_download(engine, app_client):
    assert app_client.get("/owner/kyrgyz", follow_redirects=False).status_code in (303, 302, 401, 403)
    assert app_client.get("/owner/kyrgyz.csv", follow_redirects=False).status_code in (303, 302, 401, 403)
    owner_login(app_client)
    page = app_client.get("/owner/kyrgyz").text
    assert "Кыргызские фразы на проверку" in page and "Жазылдыңыз: {when}, {who}." in page
    assert "Подтверждение записи и напоминание" in page  # the section column
    r = app_client.get("/owner/kyrgyz.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "По-кыргызски" in r.text
