"""Chat with the operator in the terminal (no Telegram needed).

Usage: python -m joop.cli [business.yaml]
"""

from __future__ import annotations

import asyncio
import sys

from anthropic import AsyncAnthropic

from .agent import Agent
from .business import BusinessProfile
from .config import Settings
from .storage import Storage


async def run() -> None:
    settings = Settings.from_env(require_telegram=False)
    business_file = sys.argv[1] if len(sys.argv) > 1 else settings.business_file
    business = BusinessProfile.from_yaml(business_file)

    async def notify(text: str) -> None:
        print(f"\n--- уведомление владельцу ---\n{text}\n-----------------------------")

    agent = Agent(
        llm=AsyncAnthropic(api_key=settings.anthropic_api_key),
        business=business,
        storage=Storage(":memory:"),
        model=settings.model,
        notifier=notify,
    )
    print(f"Чат с оператором '{business.name}'. Выход: Ctrl+C\n")
    while True:
        try:
            text = input("Клиент: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        result = await agent.reply(1, text, "terminal")
        print(f"Бот: {result.text}\n")


if __name__ == "__main__":
    asyncio.run(run())
