"""Telegram bot (aiogram 3): customer chat + owner commands."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, Message
from anthropic import AsyncAnthropic, AuthenticationError

from .agent import Agent
from .business import BusinessProfile
from .config import Settings
from .storage import Storage

log = logging.getLogger(__name__)

GREETING = (
    "Саламатсызбы! {name} байланышта. Суроо бериңиз же жазылууга жардам берем.\n"
    "Здравствуйте! Это {name}. Задайте вопрос или я помогу записаться."
)


def build_router(agent: Agent, storage: Storage, bot: Bot, owner_chat_id: int | None) -> Router:
    router = Router()

    def is_owner(message: Message) -> bool:
        return owner_chat_id is not None and message.chat.id == owner_chat_id

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(GREETING.format(name=agent.business.name))

    @router.message(Command("myid"))
    async def myid(message: Message) -> None:
        await message.answer(f"Ваш chat_id: {message.chat.id}")

    # --- owner commands -------------------------------------------------
    @router.message(Command("leads"))
    async def leads(message: Message) -> None:
        if not is_owner(message):
            return
        items = storage.recent_leads(20)
        if not items:
            await message.answer("Заявок пока нет.")
            return
        lines = [
            f"#{l.id} {l.created_at[:16]} | {l.name} | {l.phone} | {l.service} | {l.preferred_time or '-'}"
            for l in items
        ]
        await message.answer("\n".join(lines))

    @router.message(Command("export"))
    async def export(message: Message) -> None:
        if not is_owner(message):
            return
        await message.answer_document(BufferedInputFile(storage.leads_csv(), filename="leads.csv"))

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if not is_owner(message):
            return
        s = storage.stats()
        await message.answer(
            f"Чатов: {s['chats']}\nСообщений: {s['messages']}\n"
            f"Заявок: {s['leads']}\nОткрытых передач человеку: {s['handoffs_open']}"
        )

    @router.message(Command("reply"))
    async def owner_reply(message: Message, command: CommandObject) -> None:
        if not is_owner(message):
            return
        parts = (command.args or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[0].lstrip("-").isdigit():
            await message.answer("Формат: /reply <chat_id> <текст>")
            return
        chat_id, text = int(parts[0]), parts[1]
        await bot.send_message(chat_id, text)
        storage.add_message(chat_id, "assistant", f"[администратор] {text}")
        await message.answer("Отправлено.")

    @router.message(Command("resume"))
    async def resume(message: Message, command: CommandObject) -> None:
        if not is_owner(message):
            return
        arg = (command.args or "").strip()
        if not arg.lstrip("-").isdigit():
            await message.answer("Формат: /resume <chat_id>")
            return
        storage.set_handoff(int(arg), False)
        await message.answer(f"Бот снова отвечает в чате {arg}.")

    # --- customer messages ---------------------------------------------
    @router.message(F.text)
    async def on_text(message: Message) -> None:
        chat_id = message.chat.id
        user = message.from_user
        display = (user.full_name if user else "") + (f" @{user.username}" if user and user.username else "")
        storage.set_display_name(chat_id, display)

        if storage.is_handoff(chat_id):
            # A human is handling this chat: forward instead of auto-replying.
            if owner_chat_id is not None:
                await bot.send_message(
                    owner_chat_id, f"[{chat_id} {display}]: {message.text}\nОтветить: /reply {chat_id} текст"
                )
            storage.add_message(chat_id, "user", message.text)
            return

        await bot.send_chat_action(chat_id, "typing")
        try:
            result = await agent.reply(chat_id, message.text, display)
        except AuthenticationError:
            log.error("Anthropic rejected ANTHROPIC_API_KEY (401). Run: python -m joop.setup")
            await message.answer(
                "Кечиресиз, техникалык ката. Бир аздан кийин кайра жазыңыз.\n"
                "Извините, техническая ошибка. Попробуйте чуть позже."
            )
            return
        except Exception:
            log.exception("Agent failed for chat %s", chat_id)
            await message.answer(
                "Кечиресиз, техникалык ката. Бир аздан кийин кайра жазыңыз.\n"
                "Извините, техническая ошибка. Попробуйте чуть позже."
            )
            return
        await message.answer(result.text)

    @router.message()
    async def non_text(message: Message) -> None:
        await message.answer(
            "Азырынча текст гана түшүнөм.\nПока понимаю только текстовые сообщения."
        )

    return router


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    business = BusinessProfile.from_yaml(settings.business_file)
    storage = Storage(settings.db_path)
    bot = Bot(settings.telegram_token)

    async def notify_owner(text: str) -> None:
        if settings.owner_chat_id is not None:
            await bot.send_message(settings.owner_chat_id, text)

    if settings.owner_chat_id is None:
        log.warning("OWNER_CHAT_ID is not set: lead notifications are disabled. Send /myid to the bot.")

    agent = Agent(
        llm=AsyncAnthropic(api_key=settings.anthropic_api_key),
        business=business,
        storage=storage,
        model=settings.model,
        notifier=notify_owner,
    )
    dp = Dispatcher()
    dp.include_router(build_router(agent, storage, bot, settings.owner_chat_id))
    log.info("Joop AI started for '%s' (model %s)", business.name, settings.model)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
