"""Interactive first-time setup: writes .env and business.yaml.

Usage: python -m joop.setup
Secrets are typed without echo and never printed.
"""

from __future__ import annotations

import getpass
import re
import shutil
from pathlib import Path

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")


def valid_telegram_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token.strip()))


def valid_anthropic_key(key: str) -> bool:
    key = key.strip()
    return key.startswith("sk-") and len(key) > 20


def render_env(token: str, api_key: str, owner_chat_id: str = "", model: str = "claude-haiku-5-5") -> str:
    return (
        "# Created by python -m joop.setup. Never commit this file.\n"
        f"TELEGRAM_BOT_TOKEN={token.strip()}\n"
        f"ANTHROPIC_API_KEY={api_key.strip()}\n"
        f"OWNER_CHAT_ID={owner_chat_id.strip()}\n"
        f"JOOP_MODEL={model}\n"
        "BUSINESS_FILE=business.yaml\n"
        "DB_PATH=joop.db\n"
    )


def write_env(path: Path, content: str) -> None:
    if path.exists():
        backup = path.with_suffix(".bak")
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows: permissions are managed differently


def ask(prompt: str, check, secret: bool = False) -> str:
    while True:
        value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        if check(value):
            return value
        print("  Неверный формат, попробуйте ещё раз.")


def main() -> None:
    root = Path.cwd()
    print("Joop AI: первичная настройка\n")
    token = ask("Токен бота от @BotFather (ввод скрыт): ", valid_telegram_token, secret=True)
    api_key = ask("Ключ Anthropic API, начинается с sk- (ввод скрыт): ", valid_anthropic_key, secret=True)
    owner = input("Ваш chat_id (Enter, если ещё не знаете — бот покажет по /myid): ").strip()
    if owner and not owner.lstrip("-").isdigit():
        print("  chat_id должен быть числом — оставляю пустым, добавите позже.")
        owner = ""

    write_env(root / ".env", render_env(token, api_key, owner))
    print("Файл .env сохранён.")

    profile = root / "business.yaml"
    if not profile.exists():
        shutil.copy2(root / "business.example.yaml", profile)
        print("Создан business.yaml из демо-салона — замените данные на данные клиента.")

    print("\nГотово. Запуск бота:  python -m joop")
    if not owner:
        print("Потом напишите боту /myid, впишите число в OWNER_CHAT_ID в .env и перезапустите.")


if __name__ == "__main__":
    main()
