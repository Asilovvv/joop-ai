"""Settings from environment variables (.env supported)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, no overriding of real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    telegram_token: str
    anthropic_api_key: str
    owner_chat_id: int | None
    model: str
    business_file: str
    db_path: str

    @classmethod
    def from_env(cls, require_telegram: bool = True) -> "Settings":
        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if require_telegram and not token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
        if not api_key:
            raise SystemExit("ANTHROPIC_API_KEY is not set (see .env.example)")
        owner = os.getenv("OWNER_CHAT_ID", "").strip()
        return cls(
            telegram_token=token,
            anthropic_api_key=api_key,
            owner_chat_id=int(owner) if owner else None,
            model=os.getenv("JOOP_MODEL", "claude-haiku-5-5"),
            business_file=os.getenv("BUSINESS_FILE", "business.yaml"),
            db_path=os.getenv("DB_PATH", "joop.db"),
        )
