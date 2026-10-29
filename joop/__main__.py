"""Command line entry point: ``python -m joop <command>``."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from sqlmodel import select

from .config import get_settings
from .db import init_db, new_session
from .models import Business
from .presets import SlugTaken, create_business
from .profile import ProfileError, apply_profile, load_profile
from .security import hash_password


def _find(slug: str) -> Business | None:
    with new_session() as s:
        return s.exec(select(Business).where(Business.slug == slug.strip().lower())).first()


def _password(given: str | None) -> str | None:
    password = given or getpass.getpass("Пароль для входа в панель (от 8 символов): ")
    if len(password) < 8:
        print("Пароль должен быть не короче 8 символов.")
        return None
    return password


def cmd_init_db(_args) -> int:
    init_db()
    print("База данных готова.")
    return 0


def cmd_create_business(args) -> int:
    init_db()
    password = _password(args.password)
    if password is None:
        return 1
    profile = None
    if args.profile:
        try:
            profile = load_profile(args.profile)
        except (OSError, ProfileError) as exc:
            print(f"Профиль не загружен: {exc}")
            return 1
    with new_session() as s:
        try:
            business = create_business(
                s, slug=args.slug, name=args.name or (profile or {}).get("name", args.slug), password=password,
                niche=args.niche, demo=args.demo and profile is None,
            )
        except SlugTaken:
            print(f"Логин «{args.slug}» уже занят.")
            return 1
        if profile is not None:
            apply_profile(s, business, profile)
        s.commit()
        print(f"Готово. Логин панели: {business.slug}")
        print(f"Код для уведомлений в Telegram: /admin {business.admin_link_code}")
        if args.demo:
            print("Добавлены демо-прайс, врачи и окна на неделю. Замените их в панели на настоящие.")
    return 0


def cmd_import_profile(args) -> int:
    init_db()
    try:
        profile = load_profile(args.file)
    except (OSError, ProfileError) as exc:
        print(f"Профиль не загружен: {exc}")
        return 1
    with new_session() as s:
        business = s.exec(select(Business).where(Business.slug == args.slug.strip().lower())).first()
        if business is None:
            print("Компания не найдена.")
            return 1
        apply_profile(s, business, profile, replace=not args.keep)
        s.commit()
    print("Профиль загружен: прайс, вопросы и правила обновлены. Проверьте их в панели.")
    return 0


def cmd_set_password(args) -> int:
    init_db()
    password = _password(args.password)
    if password is None:
        return 1
    with new_session() as s:
        business = s.exec(select(Business).where(Business.slug == args.slug)).first()
        if business is None:
            print("Компания не найдена.")
            return 1
        business.admin_password_hash = hash_password(password)
        s.add(business)
        s.commit()
    print("Пароль обновлён.")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .web.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")
    return 0


def cmd_dev(args) -> int:
    """Admin panel on localhost plus Telegram long polling: no public address needed."""
    import uvicorn

    from .channels.polling import TelegramPoller
    from .runtime import Runtime
    from .web.app import create_app

    settings = get_settings()
    init_db()
    business = _find(args.slug)
    if business is None:
        print("Компания не найдена. Создайте её: python -m joop create-business --slug ... --name ... --demo")
        return 1
    rt = Runtime(settings)
    poller = TelegramPoller(rt, business.id)
    poller.start()
    print(f"Панель: http://127.0.0.1:{args.port}/login (логин {business.slug})")
    if not business.telegram_bot_token:
        print("Вставьте токен бота в панели на странице «Каналы» — бот заработает без перезапуска.")
    try:
        uvicorn.run(create_app(settings, rt), host="127.0.0.1", port=args.port)
    finally:
        poller.stop()
    return 0


def cmd_chat(args) -> int:
    """Talk to the agent in the terminal, as a customer would. Needs only ANTHROPIC_API_KEY."""
    from .agent.engine import handle_incoming
    from .channels.base import IncomingMessage
    from .runtime import Runtime

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("Не задан ANTHROPIC_API_KEY. Добавьте ключ в файл .env (см. .env.example).")
        return 1
    init_db()
    business = _find(args.slug)
    if business is None:
        print("Компания не найдена.")
        return 1
    rt = Runtime(settings)
    print(f"Чат с ИИ-администратором «{business.name}». Пустая строка — выход.\n")
    n = 0
    while True:
        try:
            text = input("Клиент: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        n += 1
        incoming = IncomingMessage("console", args.chat_id, "command" if text.startswith("/") else "text", text, "Тест", f"console:{args.chat_id}:{n}:{text[:20]}")
        with new_session() as s:
            b = s.get(Business, business.id)
            outcome = handle_incoming(s, b, incoming, rt.get_llm)
            s.commit()
        if outcome.reply:
            print(f"ИИ: {outcome.reply}")
        for note in outcome.admin_notes:
            print("\n[уведомление администратору]\n" + note + "\n")
        if outcome.skipped:
            print(f"(без ответа: {outcome.skipped})")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m joop", description="Joop AI: ИИ-администратор для бизнеса")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="создать таблицы базы данных").set_defaults(func=cmd_init_db)

    p = sub.add_parser("create-business", help="создать компанию и вход в панель")
    p.add_argument("--slug", required=True, help="логин компании латиницей, например aktish")
    p.add_argument("--name", help="название, например «Ак-Тиш Дент» (по умолчанию из профиля)")
    p.add_argument("--profile", help="YAML-профиль: прайс, вопросы, правила (см. business.dental.example.yaml)")
    p.add_argument("--niche", default="dental", choices=["dental", "beauty", "auto", "education", "other"])
    p.add_argument("--password", help="пароль панели (если не указать, спросит)")
    p.add_argument("--demo", action="store_true", help="добавить демо-прайс, врачей и окна")
    p.set_defaults(func=cmd_create_business)

    p = sub.add_parser("import-profile", help="загрузить прайс, вопросы и правила из YAML")
    p.add_argument("--slug", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--keep", action="store_true", help="не удалять текущий прайс и вопросы")
    p.set_defaults(func=cmd_import_profile)

    p = sub.add_parser("set-password", help="сменить пароль панели")
    p.add_argument("--slug", required=True)
    p.add_argument("--password")
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("serve", help="запустить сервер (панель и вебхуки)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("dev", help="панель на компьютере + Telegram без публичного адреса")
    p.add_argument("--slug", required=True)
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_dev)

    p = sub.add_parser("chat", help="поговорить с ИИ в терминале")
    p.add_argument("--slug", required=True)
    p.add_argument("--chat-id", default="console")
    p.set_defaults(func=cmd_chat)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
