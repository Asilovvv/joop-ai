"""Notifications go through the business's own Telegram bot: with the bot disconnected, a linked chat gets nothing.

The panel must not show such chats as working notifications (green «Уведомления: 1», a ticked launch step)."""

import re

from fastapi.testclient import TestClient

from joop import db
from joop.dispatch import alert_chats
from joop.models import Business
from joop.timeutil import utcnow
from joop.web.app import create_app
from joop.web.saas import checklist

from .test_web import login


def _set(business_id: int, **fields) -> None:
    with db.new_session() as s:
        b = s.get(Business, business_id)
        for k, v in fields.items():
            setattr(b, k, v)
        s.add(b)
        s.commit()


def _chip(page: str) -> str:
    return re.sub(r"\s+", " ", re.search(r'<span class="chip[^"]*">Уведомления:[^<]*</span>', page).group(0))


def test_alert_chats_need_the_bot(business):
    _set(business.id, admin_chat_ids="111, 222")
    with db.new_session() as s:
        assert alert_chats(s.get(Business, business.id)) == ["111", "222"]
    _set(business.id, telegram_bot_token="")  # «Отключить бота» keeps the chats for a reconnect
    with db.new_session() as s:
        b = s.get(Business, business.id)
        assert b.admin_chat_ids and alert_chats(b) == []
        assert {i["key"]: i for i in checklist(s, b, utcnow())}["admin"]["done"] is False


def test_dashboard_and_settings_say_so_when_the_bot_is_off(business, settings, rt):
    _set(business.id, admin_chat_ids="111")
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert _chip(c.get("/panel").text) == '<span class="chip ok">Уведомления: 1</span>'
        _set(business.id, telegram_bot_token="")
        page = c.get("/panel").text
        assert _chip(page) == '<span class="chip warn">Уведомления: нет</span>'
        assert re.search(r'<li class="">\s*<a href="/panel/settings">Привяжите Telegram', page)
        settings_page = re.sub(r"\s+", " ", c.get("/panel/settings").text)
        assert "Привязано чатов: 1." in settings_page and "Бот отключён: уведомления не приходят" in settings_page
        assert "общий чат клиники" not in settings_page
        assert 'value="test" disabled' in re.sub(r"\s+", " ", c.get("/panel/broadcasts").text)


def test_no_linked_chat_reads_as_none_not_as_zero_notifications(business, settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        assert _chip(c.get("/panel").text) == '<span class="chip warn">Уведомления: нет</span>'


def test_disconnecting_the_bot_says_the_alerts_stop_too(business, settings, rt):
    _set(business.id, admin_chat_ids="111")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        page = c.post("/panel/channels/telegram/disconnect", data={"csrf": token}).text
    assert "уведомления о записях и заявках больше не приходят" in re.sub(r"\s+", " ", page)
