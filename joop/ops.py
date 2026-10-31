"""Running Joop on a server: a pre-launch check and database backups.

    python -m joop check            # is the server configured for real customers? (no model call)
    python -m joop check --live     # also one tiny model call: does the Anthropic key work and have credit?
    python -m joop backup           # a consistent copy of the database now

The scheduler also makes one backup a day (joop/scheduler.py). SQLite runs in WAL mode, so copying the
database file while the server writes may give a broken copy; backups use SQLite's own backup API instead.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlparse

from .config import Settings

log = logging.getLogger(__name__)

BACKUP_PREFIX = "joop-"
MIN_SECRET = 32
MIN_OWNER_PASSWORD = 12


# --- pre-launch check --------------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    required: bool
    detail: str = ""

    @property
    def label(self) -> str:
        return "OK" if self.ok else ("НУЖНО" if self.required else "МОЖНО")


def launch_checks(settings: Settings, env: Mapping[str, str] | None = None,
                  live: Callable[[], str | None] | None = None) -> list[Check]:
    """What a server needs before real customers write to it. `live` makes one model call: None = it works."""
    env = os.environ if env is None else env
    checks: list[Check] = []

    def add(name: str, ok: bool, required: bool, detail: str = "") -> None:
        checks.append(Check(name, ok, required, "" if ok else detail))

    add("Ключ Anthropic (ANTHROPIC_API_KEY)", bool(settings.anthropic_api_key), True,
        "без него ИИ не отвечает клиентам")
    if live is not None and settings.anthropic_api_key:
        problem = live()
        add("Модель отвечает", problem is None, True, _model_problem(problem or ""))
    add("Секрет сессий (SESSION_SECRET)", len(env.get("SESSION_SECRET", "").strip()) >= MIN_SECRET, True,
        f"не короче {MIN_SECRET} символов, иначе входы в панель сбрасываются при перезапуске; "
        "создать: python -c \"import secrets; print(secrets.token_hex(32))\"")
    add("Шифрование токенов (TOKEN_ENCRYPTION_KEY)", _encryption_ok(env), True,
        "создать: python -m joop gen-key; храните копию ключа отдельно от резервных копий базы")
    https = settings.public_base_url.startswith("https://")
    add("Публичный адрес (PUBLIC_BASE_URL)", https, True,
        "нужен адрес https://ваш-домен, иначе Telegram, WhatsApp и Instagram не доставят сообщения")
    add("Защищённые cookies (SECURE_COOKIES=true)", settings.secure_cookies or not https, True,
        "при https включите SECURE_COOKIES=true")
    domain = env.get("DOMAIN", "").strip().lower()
    host = (urlparse(settings.public_base_url).hostname or "").lower()
    if domain or "DOMAIN" in env:
        add("Домен совпадает с адресом (DOMAIN)", bool(domain) and domain == host, True,
            f"DOMAIN={domain or 'пусто'}, а в PUBLIC_BASE_URL — {host or 'пусто'}; сертификат выдаётся на DOMAIN")
    add("Консоль основателя (OWNER_PASSWORD)", len(settings.owner_password) >= MIN_OWNER_PASSWORD, False,
        f"без пароля не ниже {MIN_OWNER_PASSWORD} символов консоль /owner выключена")
    add("Оповещения основателю (FOUNDER_BOT_TOKEN, FOUNDER_CHAT_ID)",
        bool(settings.founder_bot_token and settings.founder_chat_id), False,
        "без них о сбоях ИИ вы узнаете только из панели")
    add("WhatsApp и Instagram (META_VERIFY_TOKEN, META_APP_SECRET)",
        bool(settings.meta_verify_token and (settings.meta_app_secret or settings.instagram_app_secret)), False,
        "нужны только для этих каналов")
    add("Цена подписки (PRICE_SOM)", settings.price_som > 0, False, "без цены оплата картой выключена, пробный период работает")
    add("Altegio (ALTEGIO_PARTNER_TOKEN)", bool(settings.altegio_partner_token), False,
        "без общего ключа салоны подключают Altegio своим ключом")
    checks.extend(_database_checks(settings))
    return checks


def _encryption_ok(env: Mapping[str, str]) -> bool:
    from cryptography.fernet import Fernet

    key = env.get("TOKEN_ENCRYPTION_KEY", "").strip()
    try:
        Fernet(key.encode())
        return bool(key)
    except ValueError:
        return False


def _model_problem(text: str) -> str:
    low = text.lower()
    if "credit balance" in low:
        return "на счёте Anthropic нет денег: пополните баланс в console.anthropic.com"
    if "authentication" in low or "invalid x-api-key" in low or "401" in low:
        return "ключ Anthropic не принят: проверьте ANTHROPIC_API_KEY"
    return text[:300] or "модель не ответила"


def _database_checks(settings: Settings) -> list[Check]:
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from .db import get_engine
    from .migrate import _config

    try:
        with get_engine().connect() as conn:
            current = conn.execute(text("select version_num from alembic_version")).scalar()
    except Exception as exc:  # no file, no table, no permission
        return [Check("База данных", False, True, f"не открывается ({type(exc).__name__}); выполните: python -m joop migrate")]
    head = ScriptDirectory.from_config(_config()).get_current_head()
    checks = [Check("Схема базы данных", current == head, True,
                    f"версия {current}, нужна {head}: выполните python -m joop migrate")]
    path = sqlite_path(settings.database_url)
    if path is not None:
        folder = backup_dir(settings)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            writable = os.access(folder, os.W_OK)
        except OSError:
            writable = False
        checks.append(Check("Папка резервных копий", writable, True, f"нет записи в {folder}"))
    return checks


def live_model_check(settings: Settings) -> str | None:
    """One tiny call through the same client the server uses. None = the model answered."""
    from .agent.llm import AnthropicLLM

    try:
        AnthropicLLM(api_key=settings.anthropic_api_key, model=settings.model, thinking=settings.thinking,
                     effort=settings.effort).respond('Reply with the JSON {"reply": "ok"}.', [{"role": "user", "content": "ping"}])
    except Exception as exc:  # the reason goes to the owner; API error texts carry no key
        cause = getattr(exc, "__cause__", None)
        return f"{exc}" + (f" — {cause}" if cause else "")
    return None


def report(checks: list[Check]) -> tuple[str, bool]:
    """Text for the terminal and whether the server is ready (every required check passed)."""
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        tag = f"[{c.label}]"
        lines.append((f"{tag:8} {c.name.ljust(width)}" + (f"  — {c.detail}" if c.detail and not c.ok else "")).rstrip())
    ready = all(c.ok for c in checks if c.required)
    lines.append("")
    lines.append("Готово к запуску." if ready else "Не готово: исправьте пункты «НУЖНО» и запустите проверку снова.")
    return "\n".join(lines), ready


# --- backups -----------------------------------------------------------------------------------------


def sqlite_path(url: str) -> Path | None:
    """File of a SQLite database URL (sqlite:////data/joop.db -> /data/joop.db); None for other databases."""
    if not url.startswith("sqlite:///") or url in {"sqlite://", "sqlite:///:memory:"}:
        return None
    return Path(url[len("sqlite:///"):])


def backup_dir(settings: Settings) -> Path:
    if settings.backup_dir:
        return Path(settings.backup_dir)
    path = sqlite_path(settings.database_url)
    return (path.parent if path is not None else Path(".")) / "backups"


def make_backup(settings: Settings, now_utc: datetime, dest: Path | None = None) -> Path | None:
    """A consistent copy of the SQLite database as joop-YYYY-MM-DD.db; older copies beyond the limit removed.

    Returns the file, or None when the database is not SQLite (back it up with its own tools)."""
    src = sqlite_path(settings.database_url)
    if src is None:
        return None
    folder = dest or backup_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{BACKUP_PREFIX}{now_utc:%Y-%m-%d}.db"
    tmp = target.with_suffix(".db.part")
    source, copy = sqlite3.connect(src), sqlite3.connect(tmp)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    os.replace(tmp, target)
    for old in sorted(folder.glob(f"{BACKUP_PREFIX}????-??-??.db"))[:-max(1, settings.backup_keep)]:
        old.unlink()  # backup rotation only: files this function wrote, never the database itself
    log.info("Database backup written: %s", target)
    return target


def backup_due(settings: Settings, now_utc: datetime) -> bool:
    if sqlite_path(settings.database_url) is None or settings.backup_keep <= 0:
        return False
    return not (backup_dir(settings) / f"{BACKUP_PREFIX}{now_utc:%Y-%m-%d}.db").exists()
