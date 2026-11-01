"""Runtime settings, read from environment variables and an optional .env file."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Load KEY=VALUE lines from a .env file. Variables already set in the environment win."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip()) if value not in (None, "") else default
    except ValueError:
        return default


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_api_key: str
    model: str
    thinking: str
    effort: str
    session_secret: str
    secure_cookies: bool
    public_base_url: str
    meta_verify_token: str
    meta_app_secret: str
    instagram_app_secret: str
    graph_api_version: str
    whatsapp_api_base: str
    instagram_api_base: str
    telegram_api_base: str
    scheduler_enabled: bool
    scheduler_interval: int
    company_legal_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    contact_telegram: str = ""
    # SaaS: self-serve sign-up, billing, founder console
    signup_enabled: bool = True
    trial_days: int = 14
    price_som: int = 0  # monthly price; 0 = not published yet, sign-up still works with a trial
    owner_password: str = ""  # founder console password; empty = console disabled
    site_demo_daily_limit: int = 300  # visitor messages a day to the live demo on the site; 0 = demo off
    founder_bot_token: str = ""  # Telegram bot that alerts the founder when the AI stops answering (joop/health.py)
    founder_chat_id: str = ""
    altegio_partner_token: str = ""  # Joop's partner token for the Altegio API (joop/altegio.py); a salon may set its own
    altegio_api_base: str = "https://api.alteg.io/api/v1"
    stt_provider: str = ""  # speech-to-text for voice messages (joop/voice.py): "" = off, "elevenlabs"
    stt_api_key: str = ""
    stt_model: str = "scribe_v2"
    stt_api_base: str = "https://api.elevenlabs.io"
    backup_dir: str = ""  # daily SQLite backups (joop/ops.py); empty = "backups" next to the database file
    backup_keep: int = 14  # daily copies kept; 0 = no automatic backups
    billing_instructions: str = ""  # how to pay by transfer or QR, shown on the billing page
    freedompay_merchant_id: str = ""
    freedompay_secret_key: str = ""
    freedompay_api_base: str = "https://api.freedompay.kg"
    freedompay_currency: str = "KGS"
    freedompay_testing: bool = True


def settings_from_env() -> Settings:
    env = os.environ
    secret = env.get("SESSION_SECRET", "").strip()
    if not secret:
        secret = secrets.token_hex(32)
        log.warning("SESSION_SECRET is not set: using a random value, panel logins reset on restart.")
    try:
        interval = max(30, int(env.get("SCHEDULER_INTERVAL_SECONDS", "300")))
    except ValueError:
        interval = 300
    return Settings(
        database_url=env.get("DATABASE_URL", "sqlite:///./joop.db"),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", "").strip(),
        model=env.get("JOOP_MODEL", "claude-haiku-5-5").strip() or "claude-haiku-5-5",
        thinking=env.get("JOOP_THINKING", "disabled").strip().lower(),
        effort=env.get("JOOP_EFFORT", "").strip().lower(),
        session_secret=secret,
        secure_cookies=_flag(env.get("SECURE_COOKIES"), False),
        public_base_url=env.get("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        meta_verify_token=env.get("META_VERIFY_TOKEN", "").strip(),
        meta_app_secret=env.get("META_APP_SECRET", "").strip(),
        instagram_app_secret=env.get("INSTAGRAM_APP_SECRET", "").strip(),
        graph_api_version=env.get("GRAPH_API_VERSION", "v26.0").strip() or "v26.0",
        whatsapp_api_base=env.get("WHATSAPP_API_BASE", "https://graph.facebook.com").rstrip("/"),
        instagram_api_base=env.get("INSTAGRAM_API_BASE", "https://graph.instagram.com").rstrip("/"),
        telegram_api_base=env.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        scheduler_enabled=_flag(env.get("SCHEDULER_ENABLED"), True),
        scheduler_interval=interval,
        company_legal_name=env.get("COMPANY_LEGAL_NAME", "").strip(),
        contact_email=env.get("CONTACT_EMAIL", "").strip(),
        contact_phone=env.get("CONTACT_PHONE", "").strip(),
        contact_telegram=env.get("CONTACT_TELEGRAM", "").strip().lstrip("@"),
        signup_enabled=_flag(env.get("SIGNUP_ENABLED"), True),
        trial_days=_int(env.get("TRIAL_DAYS"), 14),
        price_som=_int(env.get("PRICE_SOM"), 0),
        owner_password=env.get("OWNER_PASSWORD", "").strip(),
        site_demo_daily_limit=_int(env.get("SITE_DEMO_DAILY_LIMIT"), 300),
        founder_bot_token=env.get("FOUNDER_BOT_TOKEN", "").strip(),
        founder_chat_id=env.get("FOUNDER_CHAT_ID", "").strip(),
        altegio_partner_token=env.get("ALTEGIO_PARTNER_TOKEN", "").strip(),
        altegio_api_base=env.get("ALTEGIO_API_BASE", "https://api.alteg.io/api/v1").rstrip("/"),
        stt_provider=env.get("STT_PROVIDER", "").strip().lower(),
        stt_api_key=env.get("STT_API_KEY", "").strip(),
        stt_model=env.get("STT_MODEL", "scribe_v2").strip() or "scribe_v2",
        stt_api_base=env.get("STT_API_BASE", "https://api.elevenlabs.io").strip().rstrip("/"),
        backup_dir=env.get("BACKUP_DIR", "").strip(),
        backup_keep=_int(env.get("BACKUP_KEEP_DAYS"), 14),
        billing_instructions=env.get("BILLING_INSTRUCTIONS", "").strip(),
        freedompay_merchant_id=env.get("FREEDOMPAY_MERCHANT_ID", "").strip(),
        freedompay_secret_key=env.get("FREEDOMPAY_SECRET_KEY", "").strip(),
        freedompay_api_base=env.get("FREEDOMPAY_API_BASE", "https://api.freedompay.kg").strip().rstrip("/"),
        freedompay_currency=env.get("FREEDOMPAY_CURRENCY", "KGS").strip() or "KGS",
        freedompay_testing=_flag(env.get("FREEDOMPAY_TESTING"), True),
    )


@lru_cache
def get_settings() -> Settings:
    load_dotenv(os.environ.get("JOOP_ENV_FILE", ".env"))
    return settings_from_env()
