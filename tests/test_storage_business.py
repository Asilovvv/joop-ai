from pathlib import Path

import pytest

from joop.business import BusinessProfile
from joop.storage import Storage

ROOT = Path(__file__).resolve().parent.parent


def test_history_limit_starts_with_user_turn():
    s = Storage(":memory:")
    for i in range(5):
        s.add_message(1, "user", f"q{i}")
        s.add_message(1, "assistant", f"a{i}")
    h = s.history(1, limit=3)  # last 3 = a3, q4, a4 -> trimmed to q4, a4
    assert h[0]["role"] == "user"
    assert [m["content"] for m in h] == ["q4", "a4"]


def test_history_is_per_chat():
    s = Storage(":memory:")
    s.add_message(1, "user", "one")
    s.add_message(2, "user", "two")
    assert [m["content"] for m in s.history(1)] == ["one"]


def test_leads_csv_has_header_and_bom():
    s = Storage(":memory:")
    s.add_lead(1, "Айбек", "+996555000111", "Стрижка", "завтра")
    data = s.leads_csv().decode("utf-8")
    assert data.startswith("﻿id,chat_id,name")
    assert "Айбек" in data


def test_handoff_toggle_and_stats():
    s = Storage(":memory:")
    assert not s.is_handoff(9)
    s.set_handoff(9, True, "angry")
    assert s.is_handoff(9)
    assert s.stats()["handoffs_open"] == 1
    s.set_handoff(9, False)
    assert not s.is_handoff(9)


def test_example_profile_loads_and_renders():
    p = BusinessProfile.from_yaml(ROOT / "business.example.yaml")
    rendered = p.render()
    assert p.name in rendered
    assert "Services and prices" in rendered
    assert "Booking policy" in rendered


def test_profile_requires_name():
    with pytest.raises(ValueError):
        BusinessProfile.from_dict({"description": "x"})
