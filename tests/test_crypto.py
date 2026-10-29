import pytest
from sqlalchemy import text
from sqlmodel import select

from joop import crypto, db
from joop.models import Business
from joop.presets import create_business


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    crypto.reset_key_cache()
    yield
    crypto.reset_key_cache()


def _raw(column: str, slug: str) -> str:
    with db.get_engine().connect() as conn:
        return conn.execute(text(f"select {column} from business where slug = :s"), {"s": slug}).scalar()


def test_tokens_are_encrypted_at_rest_and_readable(engine, key):
    with db.new_session() as s:
        b = create_business(s, slug="enc", name="Enc", password="secret-pass")
        b.telegram_bot_token = "123456:SECRET-TOKEN"
        b.wa_access_token = "EAAG-whatsapp"
        s.add(b)
        s.commit()
    raw = _raw("telegram_bot_token", "enc")
    assert raw.startswith("enc:v1:") and "SECRET" not in raw
    assert "whatsapp" not in _raw("wa_access_token", "enc")
    with db.new_session() as s:
        b = s.exec(select(Business).where(Business.slug == "enc")).one()
        assert b.telegram_bot_token == "123456:SECRET-TOKEN" and b.wa_access_token == "EAAG-whatsapp"
        assert b.ig_access_token == ""


def test_plain_values_from_before_still_work_and_get_encrypted(engine, monkeypatch, key):
    from joop.__main__ import cmd_encrypt_tokens

    with db.new_session() as s:
        create_business(s, slug="old", name="Old", password="secret-pass")
        s.commit()
    with db.get_engine().begin() as conn:  # a token saved before encryption was switched on
        conn.execute(text("update business set telegram_bot_token = '999:PLAIN' where slug = 'old'"))
    with db.new_session() as s:
        assert s.exec(select(Business).where(Business.slug == "old")).one().telegram_bot_token == "999:PLAIN"
    monkeypatch.setattr("joop.__main__.init_db", lambda: None)
    assert cmd_encrypt_tokens(None) == 0
    assert _raw("telegram_bot_token", "old").startswith("enc:v1:")


def test_wrong_or_missing_key_fails_loudly(engine, monkeypatch, key):
    with db.new_session() as s:
        b = create_business(s, slug="k", name="K", password="secret-pass")
        b.telegram_bot_token = "1:T"
        s.add(b)
        s.commit()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    crypto.reset_key_cache()
    with pytest.raises(crypto.KeyError_):
        crypto.decrypt(_raw("telegram_bot_token", "k"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("JOOP_ENV_FILE", "/nonexistent")
    crypto.reset_key_cache()
    with pytest.raises(crypto.KeyError_):
        crypto.decrypt(_raw("telegram_bot_token", "k"))
    assert crypto.encrypt("plain") == "plain"  # no key: stored as before
