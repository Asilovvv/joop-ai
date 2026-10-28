import pytest

from joop.agent import Agent, normalize_phone
from joop.business import BusinessProfile
from joop.storage import Storage

from .fakes import FakeLLM, response, text, tool

PROFILE = BusinessProfile.from_dict(
    {
        "name": "Test Salon",
        "description": "Salon",
        "services": [{"name": "Haircut", "price": "500"}],
    }
)


def make_agent(llm, notes=None):
    notes = notes if notes is not None else []

    async def notify(msg):
        notes.append(msg)

    return Agent(llm=llm, business=PROFILE, storage=Storage(":memory:"), model="test-model", notifier=notify), notes


async def test_plain_answer_is_returned_and_saved():
    llm = FakeLLM([response(text("Стрижка стоит 500 сом."))])
    agent, _ = make_agent(llm)
    r = await agent.reply(10, "Сколько стоит стрижка?")
    assert r.text == "Стрижка стоит 500 сом."
    assert r.lead is None and not r.handoff
    assert agent.storage.history(10) == [
        {"role": "user", "content": "Сколько стоит стрижка?"},
        {"role": "assistant", "content": "Стрижка стоит 500 сом."},
    ]
    # system prompt carries the business profile
    assert "Test Salon" in llm.calls[0]["system"]
    assert "Haircut" in llm.calls[0]["system"]


async def test_history_is_sent_on_next_turn():
    llm = FakeLLM([response(text("A1")), response(text("A2"))])
    agent, _ = make_agent(llm)
    await agent.reply(1, "Q1")
    await agent.reply(1, "Q2")
    sent = llm.calls[1]["messages"]
    assert [m["content"] for m in sent] == ["Q1", "A1", "Q2"]


async def test_save_lead_tool_stores_lead_and_notifies_owner():
    llm = FakeLLM(
        [
            response(
                text("Записываю."),
                tool("save_lead", {"name": "Айгуль", "phone": "+996 555 12-34-56", "service": "Haircut",
                                   "preferred_time": "завтра 15:00"}),
            ),
            response(text("Заявка принята, администратор подтвердит.")),
        ]
    )
    agent, notes = make_agent(llm)
    r = await agent.reply(7, "Запишите меня, Айгуль, +996 555 12-34-56, стрижка завтра в 15")
    assert r.lead is not None
    assert r.lead.phone == "+996555123456"
    assert r.text == "Заявка принята, администратор подтвердит."
    assert len(agent.storage.recent_leads()) == 1
    assert len(notes) == 1 and "Айгуль" in notes[0] and "+996555123456" in notes[0]
    # second call must contain the tool result linked to the tool_use id
    last = llm.calls[1]["messages"][-1]
    assert last["role"] == "user"
    assert last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "tu_1"


async def test_thinking_blocks_are_passed_back_with_tool_results():
    from types import SimpleNamespace

    thinking = SimpleNamespace(type="thinking", thinking="customer wants a booking", signature="sig123")
    llm = FakeLLM(
        [
            response(thinking, tool("save_lead", {"name": "Айбек", "phone": "0555 123 456", "service": "Маникюр"})),
            response(text("Заявка принята.")),
        ]
    )
    agent, notes = make_agent(llm)
    r = await agent.reply(8, "Айбек, 0555 123 456, маникюр завтра в 15:00")
    assert r.text == "Заявка принята." and r.lead is not None and len(notes) == 1
    assistant_turn = llm.calls[1]["messages"][-2]
    assert assistant_turn["role"] == "assistant"
    assert assistant_turn["content"][0] == {"type": "thinking", "thinking": "customer wants a booking", "signature": "sig123"}


async def test_invalid_phone_is_rejected_back_to_model():
    llm = FakeLLM(
        [
            response(tool("save_lead", {"name": "A", "phone": "123", "service": "Haircut"})),
            response(text("Номер некорректный, отправьте ещё раз.")),
        ]
    )
    agent, notes = make_agent(llm)
    r = await agent.reply(3, "запиши, 123")
    assert r.lead is None
    assert notes == []
    assert "ERROR" in llm.calls[1]["messages"][-1]["content"][0]["content"]


async def test_handoff_sets_flag_and_notifies():
    llm = FakeLLM(
        [
            response(tool("handoff_to_human", {"reason": "клиент недоволен"})),
            response(text("Администратор скоро ответит.")),
        ]
    )
    agent, notes = make_agent(llm)
    r = await agent.reply(5, "Позовите человека!")
    assert r.handoff
    assert agent.storage.is_handoff(5)
    assert "/resume 5" in notes[0]


async def test_empty_model_answer_falls_back_to_bilingual_message():
    llm = FakeLLM([response(text(""))])
    agent, notes = make_agent(llm)
    r = await agent.reply(1, "привет")
    assert "Администратор" in r.text and "Кечиресиз" in r.text
    # the fallback promises an administrator, so the owner is told
    assert len(notes) == 1 and "привет" in notes[0] and "/reply 1" in notes[0]


async def test_reply_cut_by_token_limit_falls_back_and_notifies_owner():
    # Seen in eval: the model spent the whole budget thinking and returned no text
    llm = FakeLLM([response(stop_reason="max_tokens")])
    agent, notes = make_agent(llm)
    r = await agent.reply(1, "Тишим ооруп, бетим шишип кетти")
    assert "Администратор" in r.text and len(notes) == 1


def test_token_ceiling_leaves_room_for_thinking():
    from joop.agent import DEFAULT_MAX_TOKENS

    agent, _ = make_agent(FakeLLM([]))
    assert agent.max_tokens == DEFAULT_MAX_TOKENS >= 2048


async def test_tool_loop_is_bounded():
    llm = FakeLLM([response(tool("handoff_to_human", {"reason": "x"}, id_=f"t{i}")) for i in range(4)])
    agent, _ = make_agent(llm)
    r = await agent.reply(1, "loop")
    assert len(llm.calls) == 4
    assert r.text  # fallback text, no crash


async def test_notifier_failure_does_not_break_reply():
    async def broken(_):
        raise RuntimeError("telegram down")

    llm = FakeLLM(
        [
            response(tool("save_lead", {"name": "B", "phone": "0555123456", "service": "Haircut"})),
            response(text("Принято.")),
        ]
    )
    agent = Agent(llm=llm, business=PROFILE, storage=Storage(":memory:"), model="m", notifier=broken)
    r = await agent.reply(1, "x")
    assert r.text == "Принято." and r.lead is not None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+996 555 12-34-56", "+996555123456"),
        ("0555 123 456", "0555123456"),
        ("12345", None),
        ("abc", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
