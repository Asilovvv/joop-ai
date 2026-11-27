"""The demo recorder's own rules (scripts/record_demo.py): what it will not film and how the film is put together.

The walk itself needs a browser, ffmpeg and the model, so it runs in its own workflow (.github/workflows/
demo-video.yml), started by hand. What is checked here is what keeps a recording honest and harmless: a stand-in
model is never called the real one, the fallback reply is never taken for an answer, the recorder's server gets
nothing of the machine's own settings but the model's, and the captions follow what is on the screen.
"""

import importlib.util
import sys
from pathlib import Path

from joop.agent.engine import ERROR_REPLY

_spec = importlib.util.spec_from_file_location("record_demo", Path(__file__).resolve().parents[1] / "scripts" / "record_demo.py")
record_demo = importlib.util.module_from_spec(_spec)
sys.modules["record_demo"] = record_demo  # dataclasses look their module up by name
_spec.loader.exec_module(record_demo)


def test_only_the_real_model_is_called_real():
    assert record_demo.model_of({}) == ("claude-haiku-5-5", True)
    assert record_demo.model_of({"JOOP_MODEL": "claude-sonnet-5-5"}) == ("claude-sonnet-5-5", True)
    other = {"LLM_PROVIDER": "openai", "JOOP_MODEL": "gemini-flash"}
    assert record_demo.model_of(other | {"LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai"}) == ("gemini-flash", True)
    # the recorder's own test: a stand-in on this machine, or anything not reached over https
    assert record_demo.model_of(other | {"LLM_BASE_URL": "http://127.0.0.1:18411/v1"}) == ("gemini-flash", False)
    assert record_demo.model_of(other | {"LLM_BASE_URL": "https://localhost:8443/v1"}) == ("gemini-flash", False)
    assert record_demo.model_of(other | {"LLM_BASE_URL": "http://models.example.com/v1"}) == ("gemini-flash", False)
    assert record_demo.model_of(other) == ("gemini-flash", False)


def test_the_fallback_reply_is_not_an_answer():
    assert record_demo.is_fallback(ERROR_REPLY)
    for line in ERROR_REPLY.splitlines():  # the Kyrgyz line or the Russian one alone
        assert record_demo.is_fallback(line)
    assert not record_demo.is_fallback("Саламатсызбы! Консультация 500 сом турат.")
    assert not record_demo.is_fallback("")


def test_a_russian_answer_to_a_kyrgyz_question_is_refused():
    assert record_demo.in_russian("Здравствуйте! Консультация и осмотр стоит 500 сом. Хотите записаться?")
    assert not record_demo.in_russian("Саламатсызбы! Консультация 500 сом турат. Кайсы күнгө жазылгыңыз келет?")
    assert not record_demo.in_russian("Консультация — 500 сом.")  # short and neutral: fine in either language


def test_times_are_read_from_a_reply_and_dates_are_not():
    reply = "Ближайшее свободное время: Сб 28.11 09:00 и 9:30 у Айгерим Садыковой; в понедельник 30.11 — с 14:00."
    assert record_demo.named_times(reply) == {"09:00", "09:30", "14:00"}
    assert record_demo.named_times("Консультация — 500 сом.") == set()


def test_the_server_gets_only_the_models_settings(tmp_path):
    machine = {"PATH": "/usr/bin", "HOME": "/home/x", "ANTHROPIC_API_KEY": "key-for-the-model", "JOOP_MODEL": "",
               "DATABASE_URL": "postgresql://real/base", "FOUNDER_BOT_TOKEN": "1:founder", "FOUNDER_CHAT_ID": "42",
               "TOKEN_ENCRYPTION_KEY": "k", "FREEDOMPAY_SECRET": "s", "OWNER_PASSWORD": "the-real-one", "JOOP_ENV_FILE": "/srv/joop/.env"}
    env = record_demo.server_env(tmp_path, 4321, machine)
    assert env["ANTHROPIC_API_KEY"] == "key-for-the-model" and "JOOP_MODEL" not in env  # empty: the default model
    assert env["DATABASE_URL"] == f"sqlite:///{tmp_path / 'demo.db'}" and env["PUBLIC_BASE_URL"] == "http://127.0.0.1:4321"
    assert env["JOOP_ENV_FILE"] == str(tmp_path / "no.env") and not (tmp_path / "no.env").exists()
    assert env["OWNER_PASSWORD"] != "the-real-one" and len(env["SESSION_SECRET"]) >= 32
    assert not {"FOUNDER_BOT_TOKEN", "FOUNDER_CHAT_ID", "TOKEN_ENCRYPTION_KEY", "FREEDOMPAY_SECRET"} & set(env)


def test_a_caption_stays_until_the_next_one():
    said = [(8.0, "site"), (12.5, "form"), (20.0, "launch")]
    assert record_demo.windows(said, start=10.0, end=31.0) == [(0.0, 2.5, "site"), (2.5, 10.0, "form"), (10.0, 21.0, "launch")]
    assert record_demo.windows([(1.0, "a"), (1.02, "b")], start=0.0, end=5.0) == [(1.02, 5.0, "b")]  # a blink is dropped
    assert record_demo.windows([], start=0.0, end=5.0) == []


def test_the_picture_sits_on_the_frame_above_its_captions():
    phone = record_demo.Clip(Path("phone.webm"), (600, 990), cut=0.4, length=12.0, captions=[(0.0, 3.5, "phone"), (3.5, 12.0, "pick")])
    graph, result = record_demo.graph(phone)
    assert graph == ("[0:v]fps=25,scale=600:990:flags=lanczos,pad=1920:1080:660:0:color=0x0b1719[s0];"
                     "[s0][1:v]overlay=0:990:enable='between(t,0.00,3.50)'[s1];"
                     "[s1][2:v]overlay=0:990:enable='between(t,3.50,12.00)'[s2]")
    assert result == "[s2]"
    silent = record_demo.Clip(Path("owner.webm"), (1920, 990), cut=0.0, length=5.0)
    assert record_demo.graph(silent) == ("[0:v]fps=25,scale=1920:990:flags=lanczos,pad=1920:1080:0:0:color=0x0b1719[s0]", "[s0]")


def test_both_languages_caption_the_same_moments():
    en, ru = record_demo.CAPTIONS["en"], record_demo.CAPTIONS["ru"]
    assert list(en) == list(ru) and set(record_demo.CARDS["en"]) == set(record_demo.CARDS["ru"])
    for words in (en, ru):
        for step, text in words.values():
            assert step.split()[-1] in "1234" and 10 <= len(text) <= 80, text  # one line of the strip
    assert [en[key][0] for key in en] == sorted(en[key][0] for key in en)  # the steps go 1, 2, 3, 4


def test_a_test_run_is_marked_on_every_picture():
    strip = record_demo.strip_html("Step 2", "A <b>question</b> in Kyrgyz", mark="TEST RUN")
    assert "A &lt;b&gt;question&lt;/b&gt; in Kyrgyz" in strip and '<span class="w">TEST RUN</span>' in strip
    assert 'class="w"' not in record_demo.strip_html("Step 2", "A question in Kyrgyz")
    card = record_demo.card_html("Demo recording", "From sign-up to a booking", "Recorded on 27.11.2026", mark="TEST RUN · not the real model")
    assert '<p class="w">TEST RUN · not the real model</p>' in card
    assert 'class="w"' not in record_demo.card_html("Demo recording", "From sign-up to a booking", "Recorded on 27.11.2026")
