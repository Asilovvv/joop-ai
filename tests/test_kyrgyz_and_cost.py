from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlmodel import select

from joop import db
from joop.agent.engine import ASK_CONTACTS_REPLY, handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.lang import fix_mixed_script, is_kyrgyz_message, looks_kyrgyz, use_kyrgyz_names
from joop.models import Business, Lead, Message, Service, Slot
from joop.profile import load_profile
from joop.pricing import add_usage, cost_usd, empty_usage

from .conftest import NOW_UTC, FakeLLM

ROOT = Path(__file__).resolve().parent.parent
RU_DRAFT = "Удаление зуба стоит 2 000 сом. Записать вас?"
KY_TRANSLATION = "Тиш жулуу 2 000 сом турат. Сизди жазып коёлубу? Атыңызды жана номериңизди жазыңыз."


def say(business, text, llm, ext, chat="1001"):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        out = handle_incoming(s, b, IncomingMessage("telegram", chat, "text", text, "", ext), lambda: llm, NOW_UTC)
        s.commit()
        return out


def usage(i, o):
    u = empty_usage()
    u["input_tokens"], u["output_tokens"] = i, o
    return u


# --- language heuristics ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["cases.yaml", "cases_dental.yaml"])
def test_message_language_matches_eval_labels(name):
    cases = yaml.safe_load((ROOT / "eval" / name).read_text("utf-8"))
    for case in cases:
        if case.get("expect_lang") == "ky":
            assert is_kyrgyz_message(case["turns"][0]), case["id"]
        elif not case["id"].startswith("mixed"):
            for turn in case["turns"]:
                assert not is_kyrgyz_message(turn), (case["id"], turn)


def test_mixed_message_with_russian_majority_is_not_kyrgyz():
    assert not is_kyrgyz_message("Саламатсызбы, маникюр сколько стоит?")
    assert is_kyrgyz_message("Рахмат")
    assert looks_kyrgyz(KY_TRANSLATION) and not looks_kyrgyz(RU_DRAFT)


# --- language guard ----------------------------------------------------------------------------------


def test_guard_rewrites_russian_reply_to_kyrgyz_message(business):
    llm = FakeLLM([AgentReply(RU_DRAFT, usage=usage(100, 20))], rewrites=[KY_TRANSLATION])
    out = say(business, "Тиш жулуу канча турат?", llm, "k1")
    assert out.reply == KY_TRANSLATION and out.language_fixed
    assert llm.rewrite_calls == [RU_DRAFT]
    assert out.usage["input_tokens"] == 130 and out.usage["output_tokens"] == 45
    with db.new_session() as s:
        last = s.exec(select(Message).order_by(Message.id.desc())).first()
        # history keeps what the customer actually received, with its cost
        assert last.text == KY_TRANSLATION and last.language_fixed
        assert last.cost_usd == pytest.approx((130 * 0.10 + 45 * 0.50) / 1_000_000)


def test_guard_skips_russian_messages_and_kyrgyz_replies(business):
    llm = FakeLLM([AgentReply(RU_DRAFT), AgentReply(KY_TRANSLATION)])
    assert say(business, "Сколько стоит удаление зуба?", llm, "k2").reply == RU_DRAFT
    out = say(business, "Тиш жулуу канча турат?", llm, "k3")
    assert out.reply == KY_TRANSLATION and not out.language_fixed
    assert llm.rewrite_calls == []


def test_guard_keeps_draft_when_rewrite_fails_or_is_not_kyrgyz(business):
    llm = FakeLLM([AgentReply(RU_DRAFT), AgentReply(RU_DRAFT)], rewrites=["Удаление зуба: 2 000 сом.", None])
    assert say(business, "Тиш жулуу канча турат?", llm, "k4").reply == RU_DRAFT
    out = say(business, "Тиш жулуу канча турат?", llm, "k5")
    assert out.reply == RU_DRAFT and not out.language_fixed


def test_guard_runs_after_booking_without_booking_twice(business):
    with db.new_session() as s:
        slot = s.exec(select(Slot).where(Slot.status == "free").order_by(Slot.start)).first()
    llm = FakeLLM(
        [AgentReply("Записала вас на четверг 09:00.", booking={"slot_id": slot.id, "name": "Гүлнара", "phone": "0555321654", "service": "чистка", "preferred_time": ""})],
        rewrites=["Сизди бейшембиге саат 09:00гө жазып койдум. Рахмат!"],
    )
    out = say(business, "Атым Гүлнара, 0555 321 654, эртең саат 9да тиш тазалоо", llm, "k6")
    assert out.booking_id and out.language_fixed and len(llm.calls) == 1


# --- booking requests (no slot) -------------------------------------------------------------------------


def test_booking_request_without_slot_creates_request_lead(business):
    llm = FakeLLM([
        AgentReply("Спасибо! Администратор перезвонит и подтвердит время.",
                   booking={"slot_id": None, "name": "Азамат", "phone": "+996 700 123 456", "service": "чистка", "preferred_time": "суббота 11:00"}),
    ])
    out = say(business, "Азамат, +996 700 123 456, в субботу в 11:00", llm, "r1")
    assert out.request_id and out.booking_id is None
    assert out.admin_notes[0].startswith("Новая заявка на запись (в нерабочее время)")
    with db.new_session() as s:
        lead = s.get(Lead, out.request_id)
        assert lead.kind == "request" and lead.customer_phone == "+996700123456"
        assert "суббота 11:00" in lead.summary


def test_booking_request_needs_name_and_phone(business):
    llm = FakeLLM([AgentReply("Заявка принята!", booking={"slot_id": None, "name": "Эрлан", "phone": "", "service": "консультация", "preferred_time": "завтра 18:00"})])
    out = say(business, "Запишите меня на консультацию завтра в 18:00, меня зовут Эрлан", llm, "r2")
    assert out.reply == ASK_CONTACTS_REPLY and out.request_id is None


def test_prompt_switches_to_request_mode_without_slots(business):
    with db.new_session() as s:
        for slot in s.exec(select(Slot)).all():
            s.delete(slot)
        s.commit()
    llm = FakeLLM([AgentReply("Здравствуйте!")])
    say(business, "Хочу записаться", llm, "r3")
    system = llm.calls[0]["system"]
    assert "Свободного времени в системе нет" in system and "slot_id = null" in system
    assert "Свободное время для записи" not in system


# --- pricing -----------------------------------------------------------------------------------------------


def test_cost_uses_published_haiku_rates():
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert cost_usd(u, "claude-haiku-5-5") == pytest.approx(0.10 + 0.50)
    assert cost_usd(empty_usage(), "some-other-model") is None
    total = empty_usage()
    add_usage(total, None)
    add_usage(total, SimpleNamespace(input_tokens=10, output_tokens=5))
    assert total["input_tokens"] == 10 and total["cache_read_input_tokens"] == 0


# --- deterministic text fixes (ported from the bot, 29 Oct 2026) ----------------------------------------


def test_mixed_script_words_are_fixed_but_latin_words_kept():
    assert fix_mixed_script("Бааsы 300 сом") == "Баасы 300 сом"
    assert fix_mixed_script("Мен алbаймын") == "Мен албаймын"
    assert fix_mixed_script("Оплата по QR, Demo Beauty Studio") == "Оплата по QR, Demo Beauty Studio"


def test_russian_service_names_in_kyrgyz_reply_are_replaced():
    names = {"Прицельный рентген-снимок": "Тиштин рентген сүрөтү"}
    reply = "Ооба, клиникада прицельный рентген-снимок жасалат. Баасы 300 сом."
    assert use_kyrgyz_names(reply, names) == "Ооба, клиникада тиштин рентген сүрөтү жасалат. Баасы 300 сом."


def test_engine_applies_text_fixes_to_kyrgyz_reply(business):
    with db.new_session() as s:
        s.exec(select(Service).where(Service.name == "Удаление зуба простое")).one().name_ky = "Тиш жулуу"
        s.commit()
    llm = FakeLLM([AgentReply("Ооба, удаление зуба простое бизде бар, бааsы 2 000 сом. Сизди жазып коёлубу?")])
    out = say(business, "Тиш жулуу барбы?", llm, "f1")
    assert out.reply == "Ооба, тиш жулуу бизде бар, баасы 2 000 сом. Сизди жазып коёлубу?"
    assert llm.rewrite_calls == []


def test_russian_reply_keeps_russian_service_names(business):
    with db.new_session() as s:
        s.exec(select(Service).where(Service.name == "Удаление зуба простое")).one().name_ky = "Тиш жулуу"
        s.commit()
    llm = FakeLLM([AgentReply("Удаление зуба простое стоит 2 000 сом.")])
    assert say(business, "Сколько стоит удаление зуба?", llm, "f2").reply == "Удаление зуба простое стоит 2 000 сом."


@pytest.mark.parametrize("name", ["business.example.yaml", "business.dental.example.yaml"])
def test_demo_profiles_have_kyrgyz_names(name):
    assert all(s.get("name_ky") for s in load_profile(ROOT / name)["services"])
