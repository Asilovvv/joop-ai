"""Encryption of channel tokens at rest (Telegram bot token, WhatsApp and Instagram access tokens).

Set TOKEN_ENCRYPTION_KEY to a Fernet key (python -m joop gen-key). Values are then stored as
"enc:v1:<token>"; a database leak alone does not give control of the businesses' bots and numbers.
Without a key, values are stored as before (plain text) and a warning is logged once.
Plain values written earlier are still read, and are encrypted on the next save
(python -m joop encrypt-tokens does it for all businesses at once).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

log = logging.getLogger(__name__)
PREFIX = "enc:v1:"


class KeyError_(RuntimeError):
    pass


@lru_cache
def _fernet() -> Fernet | None:
    from .config import load_dotenv

    load_dotenv(os.environ.get("JOOP_ENV_FILE", ".env"))  # CLI commands may run before settings are read
    key = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        log.warning("TOKEN_ENCRYPTION_KEY is not set: channel tokens are stored unencrypted.")
        return None
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise KeyError_("TOKEN_ENCRYPTION_KEY is not a valid key; create one with: python -m joop gen-key") from exc


def reset_key_cache() -> None:
    _fernet.cache_clear()


def encrypt(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    f = _fernet()
    return PREFIX + f.encrypt(value.encode()).decode() if f else value


def decrypt(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value  # empty, or written before encryption was switched on
    f = _fernet()
    if f is None:
        raise KeyError_("A channel token is encrypted, but TOKEN_ENCRYPTION_KEY is not set.")
    try:
        return f.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise KeyError_("TOKEN_ENCRYPTION_KEY does not match the key the tokens were encrypted with.") from exc


class EncryptedString(TypeDecorator):
    """A VARCHAR column whose value is encrypted on write and decrypted on read."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value) if isinstance(value, str) else value

    def process_result_value(self, value, dialect):
        return decrypt(value) if isinstance(value, str) else value


def new_key() -> str:
    return Fernet.generate_key().decode()
