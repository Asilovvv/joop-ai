"""The demo recorder's promises (scripts/record_demo.py): what it will not film, and what a film says about itself.

The walk itself needs a browser, ffmpeg and the model, so it runs in its own workflow (.github/workflows/
demo-video.yml), started by hand. Checked here, without a browser, is everything that keeps a recording honest: the
whole of step 2 against the real app with a scripted model (a wrong price, a Russian answer, a time that is not free,
the code's own sentences, a waiting-list entry in place of a booking: none of them is filmed), the mark of a test run
on every picture, and the server's environment.
"""

import html
import importlib.util
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlmodel import select

from joop import db
from joop.agent.engine import ASK_CONTACTS_REPLY, ERROR_REPLY
from joop.agent.llm import AgentReply, LLMError
from joop.models import Booking, Business, Slot
from joop.timeutil import utc_to_local

from .conftest import NOW_UTC
from .test_saas import app_client, csrf_of, saas_settings, signup  # noqa: F401  (the fixtures of the app's client)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_demo.py"
_spec = importlib.util.spec_from_file_location("record_demo", SCRIPT)
record_demo = importlib.util.module_from_spec(_spec)
sys.modules["record_demo"] = record_demo  # dataclasses look their module up by name
_spec.loader.exec_module(record_demo)
Broken = record_demo.Broken


# --- step 2 against the real app: what the recorder films and what it refuses ---------------------------------------


class Desk:
    """The owner's window without a browser: the same test chat and panel pages, over the app's test client."""

    def __init__(self, client) -> None:
        self.client, self.said = client, []

    def ask(self, text: str, key: str) -> str:
        self.said.append(key)
        answers = lambda page: re.findall(r'<div class="msg ai">(.*?)<span class="meta">', page, re.S)  # noqa: E731
        before = self.client.get("/panel/try").text
        after = self.client.post("/panel/try", data={"text": text, "csrf": csrf_of(before)}).text
        return html.unescape(answers(after)[-1]).strip() if len(answers(after)) > len(answers(before)) else ""

    def panel(self, path: str) -> str:
        return self.client.get(path).text

    def say(self, key: str, landed: bool = False) -> None:
        self.said.append(key)

    def hold(self, seconds: float) -> None:
        pass


def a_new_clinic(client) -> tuple[datetime, list[Slot]]:
    """Sign the demo clinic up; (its time now, its free times ahead, earliest first)."""
    signup(client, name=record_demo.CLINIC)
    with db.new_session() as s:
        clinic = s.exec(select(Business)).one()
        now = utc_to_local(NOW_UTC, clinic.timezone)
        free = s.exec(select(Slot).where(Slot.business_id == clinic.id, Slot.status == "free", Slot.start > now)
                      .order_by(Slot.start, Slot.id)).all()
    return now, list(free)


def said(slot: Slot) -> str:
    return f"{slot.start:%d.%m} в {slot.start:%H:%M}"


PRICE_KY = AgentReply("Консультация жана кароо 500 сом турат.")
ME = {"name": "Айбек", "phone": "0555 123 456"}


def test_a_right_walk_is_filmed_with_the_booking_at_the_earliest_time(app_client, llm):
    now, free = a_new_clinic(app_client)
    first = free[0]
    llm.replies += [PRICE_KY, AgentReply(f"Ближайшее свободное время — {said(first)}."),
                    AgentReply("Записала вас.", booking={"slot_id": first.id, **ME})]
    desk, talk = Desk(app_client), []
    record_demo.chat_scene(desk, talk, now)
    assert desk.said == ["ask_price", "price", "ask_time", "time", "ask_book", "booked"]
    assert [who for who, _text in talk] == ["customer", "ai"] * 3 and talk[1][1] == PRICE_KY.reply
    with db.new_session() as s:
        assert s.exec(select(Booking)).one().slot_id == first.id
    row = record_demo.booked(app_client.get("/panel/bookings").text, "Айбек")
    assert f"{first.start:%d.%m} {first.start:%H:%M}" in row


def test_the_ai_may_ask_to_confirm_once(app_client, llm):
    now, free = a_new_clinic(app_client)
    llm.replies += [PRICE_KY, AgentReply(f"Ближайшее свободное время — {said(free[0])}."),
                    AgentReply(f"Записать вас на {said(free[0])}?"),
                    AgentReply("Записала вас.", booking={"slot_id": free[0].id, **ME})]
    desk, talk = Desk(app_client), []
    record_demo.chat_scene(desk, talk, now)
    assert desk.said[-3:] == ["ask_book", "ask_book", "booked"] and talk[-2] == ("customer", record_demo.SAY_YES)


@pytest.mark.parametrize("answer, why", [
    ("Консультация 1 500 сом турат.", "must name 500 som"),  # another row of the price list
    ("Консультация 3 500 сомдон башталат.", "must name 500 som"),
    ("Консультация 5000 сом турат.", "must name 500 som"),
    ("Баасын администратор айтат: 0555 500 600.", "must name 500 som"),  # a phone number is not a price
    ("Стоимость консультации — 500 сом. Подобрать для вас удобное время?", "not in Russian"),
    ("Добрый день! Консультация стоит 500 сом. Записать вас?", "not in Russian"),
])
def test_a_wrong_or_russian_price_answer_is_not_filmed(app_client, llm, answer, why):
    now, _free = a_new_clinic(app_client)
    llm.replies.append(AgentReply(answer))
    desk = Desk(app_client)
    with pytest.raises(Broken, match=why):
        record_demo.chat_scene(desk, [], now)
    assert desk.said == ["ask_price"]  # no caption was said over it


def test_a_time_that_is_not_free_or_not_the_earliest_is_not_filmed(app_client, llm):
    now, free = a_new_clinic(app_client)
    later = next(s for s in free if (s.start.date(), f"{s.start:%H:%M}") != (free[0].start.date(), f"{free[0].start:%H:%M}")
                 and s.start.date() != free[0].start.date())
    for answer, why in [
        ("Свободно сегодня в 16:00.", "no such free time"),  # the example has no times left today
        (f"Ближайшее время — {later.start:%d.%m} в {later.start:%H:%M}.", "earliest free time"),
        ("Ближайшее свободное время — 15.12 в 12:00.", "no such free time"),  # «Окна» does not reach that far
        ("Подберём удобное время, напишите день.", "names no time of day"),
    ]:
        token = csrf_of(app_client.get("/panel/try").text)
        app_client.post("/panel/try/reset", data={"csrf": token})  # «Новый диалог»
        llm.replies += [PRICE_KY, AgentReply(answer)]
        desk = Desk(app_client)
        with pytest.raises(Broken, match=why):
            record_demo.chat_scene(desk, [], now)
        assert desk.said == ["ask_price", "price", "ask_time"], answer


def test_a_waiting_list_entry_is_not_a_booking(app_client, llm):
    now, free = a_new_clinic(app_client)
    callback = AgentReply("Передала администратору, вам перезвонят.", booking={"slot_id": None, **ME})
    llm.replies += [PRICE_KY, AgentReply(f"Ближайшее свободное время — {said(free[0])}."), callback, callback]
    desk = Desk(app_client)
    with pytest.raises(Broken, match="did not book Айбек"):
        record_demo.chat_scene(desk, [], now)
    assert "booked" not in desk.said
    page = app_client.get("/panel/bookings").text
    assert "Айбек" in page  # the name is on «Записи»: on the waiting list, which the old whole-page search took for a booking
    assert record_demo.booked(page, "Айбек") == "" and record_demo.upcoming(page) == []


def test_a_cancelled_booking_is_not_a_booking(app_client, llm):
    now, free = a_new_clinic(app_client)
    llm.replies += [PRICE_KY, AgentReply(f"Ближайшее свободное время — {said(free[0])}."),
                    AgentReply("Записала вас.", booking={"slot_id": free[0].id, **ME})]
    record_demo.chat_scene(Desk(app_client), [], now)
    token = csrf_of(app_client.get("/panel/try").text)
    app_client.post("/panel/try/reset", data={"csrf": token})  # «Новый диалог» cancels the test booking
    page = app_client.get("/panel/bookings").text
    assert record_demo.booked(page, "Айбек") == ""


def test_a_booking_at_another_time_than_the_earliest_is_not_filmed(app_client, llm):
    now, free = a_new_clinic(app_client)
    other = next(s for s in free if s.start != free[0].start)
    llm.replies += [PRICE_KY, AgentReply(f"Ближайшее свободное время — {said(free[0])}."),
                    AgentReply("Записала вас.", booking={"slot_id": other.id, **ME})]
    with pytest.raises(Broken, match="asked for the earliest time"):
        record_demo.chat_scene(Desk(app_client), [], now)


def test_the_codes_own_sentences_are_not_filmed_as_the_ais(app_client, llm):
    now, free = a_new_clinic(app_client)
    with db.new_session() as s:  # a time somebody else has already taken
        gone = s.get(Slot, free[-1].id)
        gone.status, gone.taken = "booked", 1
        s.add(gone)
        s.commit()
        gone_id = gone.id
    llm.replies += [PRICE_KY, AgentReply(f"Ближайшее свободное время — {said(free[0])}."),
                    AgentReply("Записала вас.", booking={"slot_id": gone_id, **ME})]
    desk, talk = Desk(app_client), []
    with pytest.raises(Broken, match="the code answered in the model's place"):
        record_demo.chat_scene(desk, talk, now)
    assert talk[-1][1].startswith("Извините, это время уже занято") and "booked" not in desk.said
    assert record_demo.engine_words(ASK_CONTACTS_REPLY) and not record_demo.engine_words(PRICE_KY.reply)


def test_a_model_that_does_not_answer_is_not_filmed(app_client, llm):
    now, _free = a_new_clinic(app_client)
    llm.replies.append(LLMError("Your credit balance is too low"))
    with pytest.raises(Broken, match="The model did not answer"):
        record_demo.chat_scene(Desk(app_client), [], now)


def test_free_times_are_read_as_the_schedule_page_shows_them(app_client):
    now, free = a_new_clinic(app_client)
    page = app_client.get("/panel/slots").text
    assert record_demo.free_times(page, now) == sorted({(s.start.date(), f"{s.start:%H:%M}") for s in free})
    hours = record_demo.working_hours(page)
    assert len(hours) == 2 and all(re.fullmatch(r"\d{2}:\d{2}", h) for h in hours) and hours[0] < hours[1]
    with db.new_session() as s:  # a time marked busy is no longer free
        slot = s.get(Slot, free[0].id)
        slot.status = "busy"
        s.add(slot)
        s.commit()
    left = record_demo.free_times(app_client.get("/panel/slots").text, now)
    same_moment = [s for s in free[1:] if s.start == free[0].start]
    assert ((free[0].start.date(), f"{free[0].start:%H:%M}") in left) == bool(same_moment)


# --- the rules themselves --------------------------------------------------------------------------------------------

FRIDAY = date(2026, 11, 27)
FREE = [(date(2026, 11, 28), "09:00"), (date(2026, 11, 28), "09:30"), (date(2026, 11, 30), "14:00")]


@pytest.mark.parametrize("reply", [
    "Ближайшее свободное время: в субботу 28.11 в 09:00 и 9:30; в понедельник 30.11 — в 14:00.",
    "Завтра в 09:00 свободно.",
    "Ближайшее время — в субботу в 9:00.",
    "Мы работаем с 09:00 до 19:00. Ближайшее свободное время — 28.11 в 09:00.",
])
def test_real_free_times_with_the_earliest_among_them_pass(reply):
    assert record_demo.times_problem(reply, FREE, FRIDAY, hours=("09:00", "19:00")) == ""


@pytest.mark.parametrize("reply, why", [
    ("Свободно сегодня в 16:00.", "no such free time"),
    ("Есть время в воскресенье 29.11 в 10:00.", "no such free time"),
    ("Свободно 15.12 в 12:00.", "no such free time"),
    ("Свободно 28.11 в 14:00.", "no such free time"),  # free on Monday, not on Saturday
    ("Есть время в понедельник 30.11 в 14:00.", "earliest free time"),
    ("Свободно в воскресенье, 28.11 в 09:00.", "another day of the week"),  # the 28th is a Saturday
    ("Подберём удобное время.", "names no time of day"),
])
def test_other_times_do_not_pass(reply, why):
    assert why in record_demo.times_problem(reply, FREE, FRIDAY, hours=("09:00", "19:00"))
    assert record_demo.times_problem("Свободно 28.11 в 09:00.", [], FRIDAY) != ""  # nothing is free at all


def test_the_price_is_a_number_of_its_own():
    for right in ("Консультация 500 сом турат.", "Консультация — 500 сом.", "Баасы 500 сом, дарыгер 09:00дө бош."):
        assert record_demo.names_price(right), right
    for wrong in ("1 500 сом", "3 500 сомдон", "5000 сом", "1500", "тел. 0555 500 600", "500-кабинет эмес, 1 200 сом", ""):
        assert not record_demo.names_price(wrong) or wrong.startswith("500"), wrong
    assert not record_demo.names_price("Консультация 1 500 сом турат.")


def test_a_russian_answer_to_a_kyrgyz_question_is_refused():
    for russian in ("Здравствуйте! Консультация и осмотр стоит 500 сом. Хотите записаться?",
                    "Стоимость консультации — 500 сом. Подобрать для вас удобное время?",
                    "Добрый день! Консультация стоит 500 сом. Записать вас?",
                    "Консультация стоит 500 сом."):
        assert record_demo.in_russian(russian), russian
    for fine in ("Саламатсызбы! Консультация 500 сом турат. Кайсы күнгө жазылгыңыз келет?",
                 "Консультация 500 сом турат.",
                 "Консультация и осмотр — 500 сом.",  # the price list's own row, short and neutral
                 "Консультация — 500 сом."):
        assert not record_demo.in_russian(fine), fine


def test_the_fallback_reply_is_not_an_answer():
    assert record_demo.is_fallback(ERROR_REPLY)
    for line in ERROR_REPLY.splitlines():  # the Kyrgyz line or the Russian one alone
        assert record_demo.is_fallback(line)
    assert not record_demo.is_fallback("Саламатсызбы! Консультация 500 сом турат.")
    assert not record_demo.is_fallback("")


def test_only_the_real_model_is_called_real():
    assert record_demo.model_of({}) == ("claude-haiku-5-5", True)
    assert record_demo.model_of({"JOOP_MODEL": "claude-sonnet-5-5"}) == ("claude-sonnet-5-5", True)
    other = {"LLM_PROVIDER": "openai", "JOOP_MODEL": "gemini-flash"}
    assert record_demo.model_of(other | {"LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai"}) == ("gemini-flash", True)
    assert record_demo.model_of(other | {"LLM_BASE_URL": "https://8.8.8.8/v1"}) == ("gemini-flash", True)
    # the recorder's own test: a stand-in on this machine or network, or anything not reached over https
    for address in ("http://127.0.0.1:18411/v1", "https://localhost:8443/v1", "http://models.example.com/v1", "",
                    "https://127.0.0.2/v1", "https://127.1/v1", "https://0.0.0.0/v1", "https://[::1]/v1",
                    "https://[::ffff:127.0.0.1]/v1", "https://localhost./v1", "https://stub.localhost/v1",
                    "https://host.docker.internal/v1", "https://192.168.1.20/v1", "https://10.0.0.5:8443/v1",
                    "https://models/v1", "https://2130706433/v1"):
        assert record_demo.model_of(other | {"LLM_BASE_URL": address}) == ("gemini-flash", False), address
    spaced = {"LLM_PROVIDER": " OpenAI ", "LLM_BASE_URL": "http://127.0.0.1:18411/v1"}  # as config.py reads it
    assert record_demo.model_of(spaced)[1] is False


def test_the_server_gets_only_the_models_settings(tmp_path):
    machine = {"PATH": "/usr/bin", "HOME": "/home/x", "ANTHROPIC_API_KEY": "key-for-the-model", "JOOP_MODEL": "",
               "DATABASE_URL": "postgresql://real/base", "FOUNDER_BOT_TOKEN": "1:founder", "FOUNDER_CHAT_ID": "42",
               "TOKEN_ENCRYPTION_KEY": "k", "FREEDOMPAY_SECRET_KEY": "s", "OWNER_PASSWORD": "the-real-one",
               "JOOP_ENV_FILE": "/srv/joop/.env", "ANTHROPIC_BASE_URL": "https://elsewhere.example.org",
               "META_APP_SECRET": "m", "TELEGRAM_BOT_TOKEN": "2:bot", "SCHEDULER_ENABLED": "1"}
    env = record_demo.server_env(tmp_path, 4321, machine)
    assert env["ANTHROPIC_API_KEY"] == "key-for-the-model" and "JOOP_MODEL" not in env  # empty: the default model
    assert env["DATABASE_URL"] == f"sqlite:///{tmp_path / 'demo.db'}" and env["PUBLIC_BASE_URL"] == "http://127.0.0.1:4321"
    assert env["JOOP_ENV_FILE"] == str(tmp_path / "no.env") and not (tmp_path / "no.env").exists()
    assert env["OWNER_PASSWORD"] != "the-real-one" and len(env["SESSION_SECRET"]) >= 32
    assert env["SCHEDULER_ENABLED"] == "0"  # no reminders or summaries from a recording
    own = {"PYTHONPATH", "JOOP_ENV_FILE", "DATABASE_URL", "SESSION_SECRET", "SECURE_COOKIES", "PUBLIC_BASE_URL",
           "OWNER_PASSWORD", "SCHEDULER_ENABLED"}
    assert set(env) <= set(record_demo.SYSTEM_ENV) | set(record_demo.MODEL_ENV) | own
    assert set(record_demo.MODEL_ENV) == {"ANTHROPIC_API_KEY", "JOOP_MODEL", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY"}


def test_a_failed_run_says_what_the_server_logged():
    log = """INFO:     Uvicorn running on http://127.0.0.1:4321
ERROR joop.agent.engine: Model call failed for business demo-stomatologiya
Traceback (most recent call last):
  File "joop/agent/llm.py", line 290, in respond
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': {'message': 'Your credit balance is too low to access the Anthropic API.'}}
  File "joop/agent/llm.py", line 301, in respond
    raise LLMError(f"Claude API call failed: {type(exc).__name__}") from exc
joop.agent.llm.LLMError: Claude API call failed: BadRequestError
ERROR joop.web.saas: The test chat fell back after an error
INFO:     127.0.0.1:5 - "POST /panel/try HTTP/1.1" 303 See Other
"""
    told = record_demo.errors_in(log)
    assert "Your credit balance is too low" in told and "raise LLMError" not in told  # the provider's words are kept
    assert "Uvicorn" not in told and "303" not in told
    assert record_demo.errors_in("INFO:     Application startup complete.") == ""
    assert len(record_demo.errors_in("ValueError: " + "x" * 900)) == 300
    assert record_demo.errors_in("KeyError: 'a'\nKeyError: 'a'\nKeyError: 'a'") == "KeyError: 'a'"
    # the walk's own stop keeps its words; anything else (a browser's timeout) is named, never left as a traceback
    assert record_demo.verdict(Broken("The model did not answer"), log).startswith("The model did not answer\nThe server's log says:\n")
    slow = record_demo.verdict(TimeoutError("Timeout 150000ms exceeded.\n  waiting for navigation"), "")
    assert slow == "TimeoutError: Timeout 150000ms exceeded.\n  waiting for navigation"


def test_a_slow_answer_gets_the_long_wait_not_the_clicks_own():
    source = SCRIPT.read_text(encoding="utf-8")
    press = source[source.index("    def press("):source.index("    def write(")]
    assert "expect_navigation(timeout=ANSWER_WAIT * 1000)" in press and "target.click(no_wait_after=True)" in press
    assert record_demo.ANSWER_WAIT >= 120  # the model's client itself gives up after three tries of forty seconds


class Window:
    """A browser page that only keeps the order of what is done to it."""

    def __init__(self, log: list) -> None:
        self.log = log

    def expect_navigation(self, timeout):
        log = self.log

        class Arrival:
            def __enter__(self):
                log.append("wait for the next page")

            def __exit__(self, *error):
                log.append("the next page is there")

        return Arrival()

    def wait_for_load_state(self, *a, **k):
        self.log.append("the page comes to rest")

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        self.log.append("the answer is brought into the window")
        return 1.0


class Button:
    def __init__(self, log: list) -> None:
        self.log = log

    def scroll_into_view_if_needed(self):
        pass

    def evaluate(self, script):
        pass

    def click(self, **how):
        self.log.append(("click", how))


def test_the_answer_is_in_the_window_before_its_caption_starts(monkeypatch):
    log: list = []
    shot = record_demo.Shot.__new__(record_demo.Shot)  # the window's own logic, without a browser
    shot.page, shot.marks, shot.landed = Window(log), [], None
    moments = iter(range(100, 200))
    monkeypatch.setattr(record_demo.time, "monotonic", lambda: next(moments))
    shot.press(Button(log), arrived=lambda: shot.page.evaluate("show"))
    assert log == ["wait for the next page", ("click", {"no_wait_after": True}), "the next page is there",
                   "the answer is brought into the window", "the page comes to rest"]
    landed = shot.landed
    shot.say("price", landed=True)  # the caption of the answer starts when the answer is in the window…
    assert shot.marks == [(landed, "price")]
    shot.say("ask_time")  # …and a later caption never starts before an earlier one
    assert shot.marks[1][0] > landed
    source = SCRIPT.read_text(encoding="utf-8")
    ask = source[source.index("    def ask("):source.index("    def close(")]
    assert "arrived=lambda: self.page.evaluate(_SHOW_ANSWER)" in ask and "seen < 0.99" in ask and "raise Broken" in ask


def test_a_caption_stays_until_the_next_one():
    marks = [(8.0, "site"), (12.5, "form"), (20.0, "launch")]
    assert record_demo.windows(marks, start=10.0, end=31.0) == [(0.0, 2.5, "site"), (2.5, 10.0, "form"), (10.0, 21.0, "launch")]
    assert record_demo.windows([(1.0, "a"), (1.02, "b")], start=0.0, end=5.0) == [(1.02, 5.0, "b")]  # a blink is dropped
    assert record_demo.windows([], start=0.0, end=5.0) == []


def test_every_caption_said_exists_in_both_languages():
    source = SCRIPT.read_text(encoding="utf-8")
    keys = set(re.findall(r'\.say\("(\w+)"', source)) | set(re.findall(r'answer\(desk, \w+, "(\w+)"', source)) | {"price_plain"}
    en, ru = record_demo.CAPTIONS["en"], record_demo.CAPTIONS["ru"]
    assert keys == set(en) == set(ru)
    assert list(en) == list(ru) and set(record_demo.CARDS["en"]) == set(record_demo.CARDS["ru"])
    for words in (en, ru):
        for step, text in words.values():
            assert step.split()[-1] in "1234" and 10 <= len(text) <= 80, text  # one line of the strip
    assert [en[key][0] for key in en] == sorted(en[key][0] for key in en)  # the steps go 1, 2, 3, 4


def test_the_cards_say_what_is_the_models_and_what_is_the_codes():
    for lang, model_word, code_word in (("en", "model", "code"), ("ru", "модел", "код")):
        end = record_demo.CARDS[lang]["end"]
        assert model_word in end and code_word in end, end  # not «every answer is the AI's own»
        note = record_demo.CARDS[lang]["note"]
        assert model_word in note and code_word in note


def test_a_test_run_is_marked_on_every_picture_the_file_and_the_dialogue():
    for lang in ("en", "ru"):
        cards = record_demo.CARDS[lang]
        test = record_demo.pictures_of(lang, "stand-in", False, "27.11.2026")
        real = record_demo.pictures_of(lang, "claude-haiku-5-5", True, "27.11.2026")
        assert set(test) == set(real) == set(record_demo.CAPTIONS[lang]) | {"title", "end"}
        for name, (page, height) in test.items():
            mark = cards["test"] if name in ("title", "end") else cards["test_short"]
            assert f'class="w">{html.escape(mark)}<' in page, name
            assert 'class="w"' not in real[name][0], name
            assert height == (record_demo.FRAME[1] if name in ("title", "end") else record_demo.BAND)
        assert html.escape(cards["end_test"]) in test["end"][0] and html.escape(cards["end"]) not in test["end"][0]
        assert html.escape(cards["end"]) in real["end"][0] and "stand-in" in test["title"][0]
        assert "TEST" in record_demo.file_name(lang, False) and "TEST" not in record_demo.file_name(lang, True)
        told = record_demo.transcript([("customer", "Салам"), ("ai", "Саламатсызбы!")], lang, "stand-in", False, "27.11.2026")
        assert cards["test"] in told and cards["end_test"] in told and "Customer: Салам\nAI: Саламатсызбы!" in told
        honest = record_demo.transcript([], lang, "claude-haiku-5-5", True, "27.11.2026")
        assert cards["test"] not in honest and cards["note"] in honest


def test_the_picture_sits_on_the_frame_above_its_captions():
    phone = record_demo.Clip(Path("phone.webm"), (600, 990), cut=0.4, length=12.0, captions=[(0.0, 3.5, "phone"), (3.5, 12.0, "pick")])
    graph, result = record_demo.graph(phone)
    assert graph == ("[0:v]fps=25,scale=600:990:flags=lanczos,pad=1920:1080:660:0:color=0x0b1719,setsar=1[s0];"
                     "[s0][1:v]overlay=0:990:enable='between(t,0.00,3.50)'[s1];"
                     "[s1][2:v]overlay=0:990:enable='between(t,3.50,12.00)'[s2]")
    assert result == "[s2]"
    silent = record_demo.Clip(Path("owner.webm"), (1920, 990), cut=0.0, length=5.0)
    assert record_demo.graph(silent) == ("[0:v]fps=25,scale=1920:990:flags=lanczos,pad=1920:1080:0:0:color=0x0b1719,setsar=1[s0]", "[s0]")
    # the cards and the clips carry one description of the picture, so the joined file has one header
    encode = " ".join(record_demo.ENCODE)
    assert "-colorspace bt470bg -color_range tv -chroma_sample_location center" in encode and "-pix_fmt yuv420p" in encode
