from datetime import datetime, time

import pytest

from joop.phone import normalize_phone
from joop.security import hash_password, new_link_code, verify_password
from joop.slots import parse_times
from joop.timeutil import fmt_slot, is_off_hours, local_to_utc, parse_days_off, parse_hhmm, utc_to_local


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0555 123 456", "+996555123456"),
        ("555123456", "+996555123456"),
        ("+996 (555) 12-34-56", "+996555123456"),
        ("996700112233", "+996700112233"),
        ("8 701 123 45 67", "+77011234567"),
        ("+49 30 1234567", "+49301234567"),
        ("12345", None),
        ("", None),
        (None, None),
        ("позвоните мне", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_password_roundtrip():
    stored = hash_password("korrekt-hors")
    assert verify_password("korrekt-hors", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")
    assert len(new_link_code()) == 8


def test_time_helpers():
    assert parse_hhmm("9") == time(9, 0)
    assert parse_hhmm("09.30") == time(9, 30)
    assert parse_hhmm("25:00") is None
    assert parse_days_off("6, 7, 9") == {6, 7}
    wed_night = datetime(2026, 11, 4, 23, 14)
    wed_day = datetime(2026, 11, 4, 11, 0)
    sunday = datetime(2026, 11, 8, 11, 0)
    assert is_off_hours(wed_night, "09:00", "19:00", "7")
    assert not is_off_hours(wed_day, "09:00", "19:00", "7")
    assert is_off_hours(sunday, "09:00", "19:00", "7")
    assert fmt_slot(datetime(2026, 11, 5, 10, 0)) == "Чт 05.11 10:00"
    local = utc_to_local(datetime(2026, 11, 4, 17, 14), "Asia/Bishkek")
    assert local == datetime(2026, 11, 4, 23, 14)
    assert local_to_utc(local, "Asia/Bishkek") == datetime(2026, 11, 4, 17, 14)


def test_parse_times():
    assert parse_times("10:00, 11.30 9; 10:00 bad") == [time(9, 0), time(10, 0), time(11, 30)]
