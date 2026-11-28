"""The launch checklist (joop/web/saas.py) in Kyrgyz, for the owner's app when its language is Kyrgyz.

The panel is in Russian and builds the steps' titles and hints there. The steps also carry their facts as fields
(how many prices and of them the example's, what is still empty or the example's, free times), and this module says
the same in Kyrgyz from those fields and the business itself. A step it does not know keeps its Russian text: better
Russian than a wrong word. All of it was written without a native speaker: check with one. The founder's «Кыргызча»
page (joop/ky_phrases.py) lists it: the names with KY and the sentences it reads as Kyrgyz.
"""

from __future__ import annotations

from typing import Any

from .models import Business
from .niches import Pack
from .web.menu import PEOPLE_KY

CATALOG_KY = {  # pack.catalog_label
    "Услуги": "Кызматтар", "Каталог": "Каталог", "Меню и цены": "Меню жана баалар", "Прайс": "Баалар",
    "Тарифы": "Тарифтер", "Курсы": "Курстар", "Курсы и цены": "Курстар жана баалар",
    "Абонементы и услуги": "Абонементтер жана кызматтар", "Номера и цены": "Бөлмөлөр жана баалар",
    "Занятия и абонементы": "Сабактар жана абонементтер", "Группы и цены": "Топтор жана баалар",
    "Анализы и цены": "Анализдер жана баалар", "Объекты": "Объекттер", "Меню": "Меню", "Туры": "Турлар",
}
ONLINE_KY = {"QR-меню": "QR-меню", "Каталог онлайн": "Онлайн каталог", "Прайс онлайн": "Онлайн баалар"}  # pack.online_label

WORDS_KY = {"address": "дарек", "phone": "телефон", "hours": "иш убактысы"}
TITLES_KY = {  # the steps whose title has no number in it
    "contacts": "Байланыш жана иш убактысы", "slots": "Жазылуу үчүн бош убакыттар", "try": "ИИни тесттик чатта текшериңиз",
    "telegram": "Telegram-ботту туташтырыңыз", "admin": "Өтүнмөлөрдү Telegram аркылуу алыңыз",
    "real": "Биринчи чыныгы кардар", "pay": "Төлөм", "free": "Акысыз тариф: бир чебер, мөөнөтсүз",
}


def _of_example(n: int) -> str:
    return f", анын ичинен мисал: {n}" if n else ""


def _contacts(step: dict, b: Business) -> tuple[str, str]:
    left = [WORDS_KY[f] for f in step.get("empty", [])]
    example = step.get("from_example", [])
    if "hours" in example:
        left.append(f"иш убактысы (азыр мисалдан: {b.hours_text})")
    left += [f"{WORDS_KY[f]} (азыр мисалдан: {getattr(b, f)})" for f in ("address", "phone") if f in example]
    if "policy" in example:
        left.append(f"жазылуу тартиби (азыр мисалдан: {b.booking_policy})")
    if "order" in example:
        terms = [f"{word} {value} сом" for word, value in (("минималдуу буйрутма", b.min_order), ("жеткирүү", b.delivery_fee),
                                                          ("акысыз жеткирүү, сомдон баштап", b.free_delivery_from)) if value]
        left.append(f"буйрутма шарттары (азыр мисалдан: {', '.join(terms)})")
    hint = ("Дагы көрсөтүңүз: " + ", ".join(left) + ". " if left else "") + "ИИ бул жерде жазылгандар менен гана жооп берет."
    return TITLES_KY["contacts"], hint


def _act(pack: Pack) -> str:
    """What to try in the test chat, as saas.checklist's `act`."""
    if pack.by_day:
        return "залды күнгө брондоңуз"
    if pack.rental:
        return "машина брондоңуз"
    if pack.has("stay"):
        return "бөлмө брондоңуз"
    if pack.has("order") and not pack.has("booking"):
        return "буйрутма бериңиз"
    return "өтүнмө калтырыңыз" if not pack.has("booking") else "жазылыңыз"


def kyrgyz(steps: list[dict[str, Any]], b: Business, pack: Pack) -> list[dict[str, Any]]:
    """The same steps with Kyrgyz titles and hints; everything else as it was."""
    people = PEOPLE_KY.get(pack.resource_label, pack.resource_label)
    bot = f"t.me/{b.telegram_bot_username}" if b.telegram_bot_token and b.telegram_bot_username else ""
    out = []
    for step in steps:
        key, n, ex = step.get("key"), step.get("count", 0), step.get("example_count", 0)
        text: tuple[str, str] | None = None
        if key == "contacts":
            text = _contacts(step, b)
        elif key == "prices":
            text = (f"{CATALOG_KY.get(pack.catalog_label, pack.catalog_label)}: {n}{_of_example(ex)}",
                    "Тесттик чат дароо жооп бериши үчүн мисал коштук. ИИ аны чыныгы кардарларга айтпайт: бааларды жана "
                    "аталыштарды өзүңүздүкүнө алмаштырыңыз — кыргызча аталыштар каалооңуз боюнча.")
        elif key == "rooms":
            text = (f"{people}: {n}{_of_example(ex)}",
                    "Бул сиздин тармактан мисал: ИИ аны чыныгы кардарларга сунуштабайт жана брондобойт. Өзүңүздүкүн "
                    "жазыңыз — аталышы, сыйымдуулугу жана канчасы бар." if ex else "Кардарлар брондогон нерсени жазыңыз.")
        elif key == "staff":
            booking = pack.has("booking")
            text = (f"{people}: {n}{_of_example(ex)}",
                    "Бул сиздин тармактан мисал: ИИ бул кишилерди чыныгы кардарларга атабайт жана аларга жазбайт. "
                    "Өзүңүздүкүлөрдү жазыңыз — аты жана эмне менен алектенет"
                    + ("." if booking else " — же жөн гана мисалды өчүрүңүз.") if ex
                    else "Кардарлар жазыла турган кишилерди жазыңыз." if booking
                    else "Кардарлар аларды аты менен сураса, өз кишилериңизди жазсаңыз болот.")
        elif key == "slots":
            text = (TITLES_KY["slots"],
                    f"Алдыда бош убакыттар: {n}." if n else "ИИ кардарларды кишилериңиздин бош убактыларына гана жазат: "
                    "жакынкы күндөрдүн убактысын ачыңыз.")
        elif key == "try":
            text = (TITLES_KY["try"],
                    f"Кардардай жазыңыз: орусча жана кыргызча, баасын сураңыз, {_act(pack)}.")
        elif key == "telegram":
            text = (TITLES_KY["telegram"],
                    "Бир аракет: @BotFather берген токенди коюңуз. WhatsApp жана Instagram — «Каналдар» бөлүмүндө.")
        elif key == "admin":
            text = (TITLES_KY["admin"],
                    "Басыңыз — ботуңуз ачылат; андан «Start» басыңыз, ошондо жаңы жазылуулар жана өтүнмөлөр сизге келип "
                    "турат." if step.get("external") else "Адегенде ботту туташтырыңыз: андан кийин бул жерде Telegram "
                    "аккаунтуңузду байлай турган баскыч пайда болот.")
        elif key == "real":
            text = (TITLES_KY["real"],
                    (f"Боттун шилтемеси: {bot} — аны Instagram профилине жана 2ГИСке коюңуз. " if bot else "")
                    + ("Унаадагы жана визиткадагы QR-коддуу чаптама — биринчи кардарга эң тез жол." if pack.comes_to_client
                       else "Кассанын жанындагы QR-коддуу тактача — биринчи кардарга эң тез жол."))
        elif key == "pay":
            text = ((TITLES_KY["free"], "Экинчи чебер жана Joop колу коюлбаган жооптор — акы төлөнүүчү тарифте.")
                    if step.get("free") else (TITLES_KY["pay"], "Сыноо мезгилинен кийин ИИ жазылуу боюнча иштейт."))
        out.append({**step, "title": text[0], "hint": text[1]} if text else step)
    return out


def online_label(pack: Pack) -> str:
    return ONLINE_KY.get(pack.online_label, pack.online_label)
