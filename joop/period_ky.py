"""The panel's line about the end of the trial or paid month (joop/period_end.banner) in Kyrgyz, for the owner's app
when its language is Kyrgyz: the line that says the AI is about to stop or has stopped for payment must be read.

period_end words it in Russian with the dates, the days left and the masters at work in it; each form here is that
sentence as a pattern, said in Kyrgyz with the same numbers. A line it does not know stays Russian.
tests/test_mobile_period_ky.py builds every form period_end has and checks each is known. Written without a native
speaker: the founder's «Кыргызча» page (joop/ky_phrases.py) lists it for one to check.
"""

from __future__ import annotations

import re

WHAT_KY = {"пробный период": "Сыноо мезгили", "оплаченный период": "Төлөнгөн мезгил"}
_WHAT = r"(Пробный период|Оплаченный период|пробный период|оплаченный период)"
_DAY = r"(\d\d\.\d\d)"
_TIME = r"(\d\d:\d\d)"

# (the Russian sentence, its Kyrgyz; {what} is the period's name, {what_l} the same mid-sentence, {0}… the other groups)
KY_PERIOD = [
    (r"ИИ не отвечает клиентам: доступ приостановлен\. Напишите нам\.",
     "ИИ кардарларга жооп бербей жатат: кирүү убактылуу токтотулган. Бизге жазыңыз."),
    (r"ИИ не отвечает клиентам: бесплатный тариф — для одного мастера, а работают (\d+)\. Оплатите подписку или оставьте "
     r"одного мастера в «Расписании»\.",
     "ИИ кардарларга жооп бербей жатат: акысыз тариф бир чебер үчүн, ал эми {0} чебер иштейт. Жазылууну төлөңүз же "
     "бир гана чеберди калтырыңыз."),
    (r"ИИ не отвечает клиентам: подписка отменена\. Сообщения из Telegram и с сайта приходят вам — отвечайте в "
     r"«Диалогах»\. Возобновить можно в «Оплате»\.",
     "ИИ кардарларга жооп бербей жатат: жазылуу жокко чыгарылган. Telegram жана сайттагы билдирүүлөр сизге келет — "
     "«Диалогдор» бөлүмүндө жооп бериңиз. «Төлөм» бөлүмүндө кайра улантсаңыз болот."),
    (rf"{_WHAT} заканчивается {_DAY} в {_TIME} — осталось (\d+) (?:день|дня|дней)\. Без оплаты ИИ остановится {_DAY}\.",
     "{what} {0} күнү саат {1} бүтөт — {2} күн калды. Төлөм болбосо, ИИ {3} күнү токтойт."),
    (rf"{_WHAT} закончился {_DAY}\. ИИ отвечает клиентам до {_DAY} {_TIME}, потом остановится\.",
     "{what} {0} күнү бүттү. ИИ кардарларга {1} күнү саат {2} болгуча жооп берет, андан кийин токтойт."),
    (rf"ИИ не отвечает клиентам с {_DAY}: {_WHAT} закончился\. Сообщения из Telegram и с сайта приходят вам — "
     r"отвечайте в «Диалогах»\.",
     "ИИ {0} күнү токтоду, кардарларга жооп бербей жатат: {what_l} бүттү. Telegram жана сайттагы билдирүүлөр сизге "
     "келет — «Диалогдор» бөлүмүндө жооп бериңиз."),
]
WAITING = (r"Заявка на оплату №(\d+) ждёт подтверждения перевода: подписка продлится, как только он придёт\. Уже "
           r"перевели — ничего делать не нужно\.",
           "№{0} төлөм өтүнмөсү которуунун ырасталышын күтүп жатат: которуу келээр замат жазылуу узартылат. Которуп "
           "койгон болсоңуз — эч нерсе кылуунун кереги жок.")
_PATTERNS = [(re.compile(rf"^{ru}$"), ky) for ru, ky in KY_PERIOD]
_WAITING = re.compile(rf"^(.*) {WAITING[0]}$", re.S)


def _one(text: str) -> str | None:
    for pattern, ky in _PATTERNS:
        found = pattern.match(text)
        if found:
            groups = list(found.groups())
            what = next((WHAT_KY[g.lower()] for g in groups if g and g.lower() in WHAT_KY), "")
            rest = [g for g in groups if not (g and g.lower() in WHAT_KY)]
            return ky.format(*rest, what=what, what_l=what[:1].lower() + what[1:])
    return None


def kyrgyz(text: str) -> str:
    """The line in Kyrgyz, or as it was when its form is not known."""
    waiting = _WAITING.match(text)
    if waiting:  # «… Заявка на оплату №N ждёт подтверждения перевода …» after the period's own sentence
        head = _one(waiting.group(1))
        return f"{head} {WAITING[1].format(waiting.group(2))}" if head else text
    return _one(text) or text
