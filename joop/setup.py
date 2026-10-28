"""Interactive setup: writes .env and business.yaml.

Usage:
    python -m joop.setup          ask for settings (Enter keeps a valid existing value)
    python -m joop.setup --check  exit 1 if .env is missing or invalid (used by start.command)
Secrets are typed without echo and never printed.
"""

from __future__ import annotations

import getpass
import re
import shutil
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
# Claude Console keys start with sk-ant- (workspace keys: sk-ant-api03-...,
# personal and service account keys use other sk-ant-* prefixes).
KEY_PREFIX = "sk-ant-"


def valid_telegram_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token.strip()))


def valid_anthropic_key(key: str) -> bool:
    key = key.strip()
    return key.startswith(KEY_PREFIX) and len(key) > 40 and not re.search(r"\s", key)


def valid_chat_id(value: str) -> bool:
    return value == "" or value.lstrip("-").isdigit()


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


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def check_env(values: dict[str, str]) -> list[str]:
    """Return a list of problems (empty = config is usable)."""
    problems = []
    if not valid_telegram_token(values.get("TELEGRAM_BOT_TOKEN", "")):
        problems.append("TELEGRAM_BOT_TOKEN отсутствует или неверного формата")
    if not valid_anthropic_key(values.get("ANTHROPIC_API_KEY", "")):
        problems.append(f"ANTHROPIC_API_KEY отсутствует или неверного формата (должен начинаться с {KEY_PREFIX})")
    return problems


def write_env(path: Path, content: str) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(".bak"))
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows: permissions are managed differently


def ask(prompt: str, check, secret: bool = False, current: str = "") -> str:
    """Ask until the value passes `check`. Empty input keeps a valid `current`."""
    keep = current and check(current)
    if keep:
        prompt = prompt.rstrip(": ") + " [Enter — оставить текущий]: "
    while True:
        value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        if not value and keep:
            return current
        if check(value):
            return value
        print("  Неверный формат, попробуйте ещё раз.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path.cwd()
    env_path = root / ".env"
    current = read_env(env_path)

    if "--check" in argv:
        problems = check_env(current) if current else ["файл .env не найден"]
        for p in problems:
            print(f"Настройка: {p}")
        return 1 if problems else 0

    print("Joop AI: настройка\n")
    token = ask("Токен бота от @BotFather (ввод скрыт): ", valid_telegram_token, True,
                current.get("TELEGRAM_BOT_TOKEN", ""))
    api_key = ask(f"Ключ Anthropic API, начинается с {KEY_PREFIX} (ввод скрыт): ", valid_anthropic_key, True,
                  current.get("ANTHROPIC_API_KEY", ""))
    owner = ask("Ваш chat_id (Enter, если ещё не знаете — бот покажет по /myid): ", valid_chat_id, False,
                current.get("OWNER_CHAT_ID", ""))

    write_env(env_path, render_env(token, api_key, owner, current.get("JOOP_MODEL", "claude-haiku-5-5")))
    print("Файл .env сохранён.")

    profile = root / "business.yaml"
    if not profile.exists():
        shutil.copy2(root / "business.example.yaml", profile)
        print("Создан business.yaml из демо-салона — замените данные на данные клиента.")

    print("\nГотово. Запуск бота:  python -m joop")
    if not owner:
        print("Потом напишите боту /myid, впишите число в OWNER_CHAT_ID в .env и перезапустите.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
