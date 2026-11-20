"""A copy of the daily backup that survives the server: encrypted and sent to the founder's Telegram.

The daily backup (joop/ops.py) lives on the same disk as the database, so a dead disk or a deleted server takes
both. When the founder bot is set up (FOUNDER_BOT_TOKEN, FOUNDER_CHAT_ID) and TOKEN_ENCRYPTION_KEY is set, the copy
is compressed, encrypted with that key and sent to the founder chat as a file, silently. Customers' names and
phone numbers are in it, so it is never sent unencrypted. Restore: python -m joop restore-copy <file> --out joop.db,
with the same TOKEN_ENCRYPTION_KEY (keep a copy of the key outside the server, docs/deploy.md)."""

from __future__ import annotations

import gzip
import logging
import os
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

SUFFIX = ".gz.enc"
MAX_BYTES = 49 * 1024 * 1024  # Telegram bots upload files up to 50 MB


class CopyError(Exception):
    """A message for the person restoring a copy."""


def _key() -> Fernet | None:
    key = (os.environ.get("TOKEN_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except ValueError:
        return None


def ready(settings) -> bool:
    return bool(settings.backup_to_telegram and settings.founder_bot_token and settings.founder_chat_id
                and _key() is not None)


def seal(data: bytes, key: Fernet) -> bytes:
    return key.encrypt(gzip.compress(data, compresslevel=6))


def unseal(data: bytes, key: Fernet) -> bytes:
    try:
        return gzip.decompress(key.decrypt(data))
    except InvalidToken as exc:
        raise CopyError("Ключ не подходит: нужен тот TOKEN_ENCRYPTION_KEY, что был на сервере в день копии.") from exc


def send(http: httpx.Client, settings, backup: Path) -> bool:
    """Send one daily backup to the founder chat. False when not set up, too large or not delivered (logged)."""
    if not ready(settings):
        return False
    key = _key()
    sealed = seal(backup.read_bytes(), key)
    name = backup.name + SUFFIX
    base = f"{settings.telegram_api_base.rstrip('/')}/bot{settings.founder_bot_token}"
    if len(sealed) > MAX_BYTES:
        text = (f"Joop AI: резервная копия базы {backup.name} больше 50 МБ и в Telegram не помещается. "
                "Скачивайте её с сервера раз в неделю (docs/deploy.md, раздел «Резервные копии»).")
        _post(http, f"{base}/sendMessage", json={"chat_id": settings.founder_chat_id, "text": text})
        return False
    caption = (f"Резервная копия базы {backup.name[len('joop-'):-len('.db')]}, зашифрована ключом TOKEN_ENCRYPTION_KEY. "
               "Восстановить: python -m joop restore-copy <файл> --out joop.db")
    ok = _post(http, f"{base}/sendDocument",
               data={"chat_id": settings.founder_chat_id, "caption": caption, "disable_notification": "true"},
               files={"document": (name, sealed, "application/octet-stream")})
    if ok:
        log.info("Encrypted backup sent to the founder chat: %s (%d bytes)", name, len(sealed))
    return ok


def _post(http: httpx.Client, url: str, **kwargs) -> bool:
    try:
        response = http.post(url, timeout=120.0, **kwargs)
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Backup copy to Telegram failed: %s", type(exc).__name__)  # the URL holds the token
        return False
    if not data.get("ok"):
        log.warning("Backup copy to Telegram rejected: %s", data.get("description", "unknown"))
        return False
    return True


def restore(src: Path, out: Path) -> Path:
    """Decrypt a copy from the founder chat into a database file; never overwrites an existing file."""
    key = _key()
    if key is None:
        raise CopyError("Задайте TOKEN_ENCRYPTION_KEY (тот, что был на сервере) в .env или окружении.")
    if out.exists():
        raise CopyError(f"{out} уже есть: укажите другой --out, чтобы не затереть базу.")
    data = unseal(src.read_bytes(), key)
    if not data.startswith(b"SQLite format 3\x00"):
        raise CopyError("Расшифровано, но это не база SQLite.")
    out.write_bytes(data)
    return out
