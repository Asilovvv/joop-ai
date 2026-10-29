"""Telegram long polling, for running on a laptop without a public HTTPS address."""

from __future__ import annotations

import logging
import threading

from ..db import new_session
from ..dispatch import process_incoming
from ..models import Business
from ..runtime import Runtime
from .telegram import parse_update

log = logging.getLogger(__name__)


class TelegramPoller(threading.Thread):
    def __init__(self, rt: Runtime, business_id: int) -> None:
        super().__init__(daemon=True, name="telegram-poller")
        self.rt = rt
        self.business_id = business_id
        self._stop = threading.Event()

    def run(self) -> None:  # pragma: no cover - network loop
        offset: int | None = None
        prepared_token = ""
        while not self._stop.is_set():
            with new_session() as session:
                business = session.get(Business, self.business_id)
            client = self.rt.telegram(business) if business else None
            if client is None:
                self._stop.wait(5)  # token not set yet: check again soon
                continue
            if business.telegram_bot_token != prepared_token:
                client.delete_webhook()  # polling and webhooks cannot run at the same time
                prepared_token = business.telegram_bot_token
                offset = None
                me = client.get_me() or {}
                log.info("Polling Telegram as @%s", me.get("username", "?"))
            updates = client.get_updates(offset, timeout=25)
            if updates is None:
                self._stop.wait(5)
                continue
            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                incoming = parse_update(update)
                if incoming is not None:
                    process_incoming(self.rt, self.business_id, incoming)

    def stop(self) -> None:
        self._stop.set()
