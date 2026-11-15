"""Password hashing and random codes (standard library only)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
    except (AttributeError, ValueError):
        return False
    if algo != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def new_link_code() -> str:
    """8-digit code an admin sends to the Telegram bot to receive notifications."""
    return f"{secrets.randbelow(10**8):08d}"


def new_test_code() -> str:
    """The secret in the panel's «Написать боту» link; Telegram allows A-Z, a-z, 0-9, _ and - in a start payload."""
    return secrets.token_urlsafe(9)


def same_secret(given: str, expected: str) -> bool:
    """Constant-time comparison that also works for non-ASCII input: hmac.compare_digest raises on such strings,
    which turned a request with a stray character in a header or a form field into a 500 instead of a refusal."""
    return hmac.compare_digest((given or "").encode("utf-8"), (expected or "").encode("utf-8"))


def new_secret() -> str:
    """URL-safe secret, valid as a Telegram webhook secret_token."""
    return secrets.token_urlsafe(24)
