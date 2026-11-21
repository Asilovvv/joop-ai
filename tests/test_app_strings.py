"""The mobile app's Kyrgyz texts in the native speaker's list (joop/app_strings.py, /owner/kyrgyz).

Before, the list held the server's phrases only: the app's ~250 Kyrgyz texts, none written by a native speaker,
were in no list at all."""

import json
import re

from joop import app_strings, ky_phrases


def test_the_snapshot_matches_the_apps_texts():
    now = [{"line": n, "ky": ky, "ru": ru} for n, ky, ru in app_strings.pairs(app_strings.DART.read_text(encoding="utf-8"))]
    kept = json.loads(app_strings.SNAPSHOT.read_text(encoding="utf-8"))  # lines too: the list says where each text is
    assert kept == now, "the app's texts changed: run  python -m joop.app_strings  and commit joop/app_ky_strings.json"


def test_texts_are_paired_with_their_russian_twin():
    rows = {ky: ru for _, ky, ru in app_strings.pairs(app_strings.DART.read_text(encoding="utf-8"))}
    assert rows["Кайталоо"] == "Повторить"  # a plain entry: the same name in the Russian set
    assert rows["Сервер менен байланыш жок ($server)"] == "Нет связи с сервером ($server)"  # _kyName beside _ruName
    assert rows["Аткарылды"] in ("Выполнен", "Выполнено", "Готово")  # a map entry: the same key
    assert rows["1 саатка"] == "1 час"  # several texts in one function, in order
    assert rows["$n түн"] == "ночь / ночи / ночей"  # Russian forms after a number: all of them
    months = next(ky for ky in rows if ky.startswith("январь"))
    assert months.endswith("декабрь") and months.count(",") == 11  # one line, not twelve
    # interpolations are {…}, never cut strings; the one apostrophe allowed is a Kyrgyz ending on a Latin name
    assert not any("'" in re.sub(r"(?<=[A-Za-z])'(?=[а-яөүң])", "", ky) for ky in rows)
    assert rows["адамдарга берилген суроо"] == "{вопрос передан / вопроса передано / вопросов передано} людям"
    assert any("залдарды" in ky for ky in rows)  # words inside ${…} reach the speaker too


def test_the_dart_reader_on_its_own():
    source = """
  static const ru = S._(
    a: 'Один',
    b: _ruB,
    c: 'Длинный ' 'текст',
  );
  static const ky = S._(
    a: 'Бир', // comment: 'not a text'
    b: _kyB,
    c: 'Узун ' 'текст',
  );
}

String _ruB(int n) => '${n > 1 ? 'много' : 'один'} раз';
String _kyB(int n) => '$n жолу';
/// next
"""
    assert app_strings.pairs(source) == [(8, "Бир", "Один"), (15, "$n жолу", "{много / один} раз"), (10, "Узун текст", "Длинный текст")]


def test_the_list_for_the_speaker_has_the_app(phrases=None):
    app = [p for p in ky_phrases.collect() if p.where.startswith("mobile/")]
    assert len(app) > 200 and {p.section for p in app} == {"Приложение для телефона"}
    assert all(p.ru for p in app) and ky_phrases.to_csv(app).count("\n") == len(app) + 1
