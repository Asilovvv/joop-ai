"""Glue between channels and the engine: process a message, then deliver the reply and notifications."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime

from . import voice
from .agent.engine import Outcome, _already_seen as already_seen, blocked, chat_turn, handle_incoming
from .billing import access_ok
from .timeutil import utcnow
from .channels.base import CHANNEL_NAMES, IncomingMessage
from .channels.telegram import bot_id
from sqlmodel import Session

from .db import free, new_session
from .models import Business
from .runtime import Runtime

log = logging.getLogger(__name__)


# --- one thread for a chat, however many messages arrive --------------------------------------------------------
# Every message from a webhook is a task in the server's shared thread pool (40 threads; the panel's pages run in it
# too). A chat is answered one message at a time, so fifty messages sent to one chat held fifty threads, each waiting
# for its turn for up to CHAT_WAIT: one chat could stop every answer and every page of the server. Now a message that
# arrives while its chat is being answered is left in the chat's queue and its thread goes back to the pool at once;
# the thread that is answering takes the queue, in arrival order, when it is done.

MAX_QUEUED = 50  # messages of one chat waiting behind the one being answered: more is not a person typing
STUCK_AFTER = 300.0  # seconds one message may be in work before the chat's next message stops waiting behind it


class _Queue:
    """The messages of one chat waiting behind the one in work."""

    __slots__ = ("waiting", "since", "dropped")

    def __init__(self, waiting: deque) -> None:
        self.waiting = waiting
        self.since = time.monotonic()  # when the message in work was taken
        self.dropped = 0


_queues: dict[tuple[int, str, str], _Queue] = {}  # the chats being answered right now (one process: memory is enough)
_queues_guard = threading.Lock()


def process_incoming(rt: Runtime, business_id: int, incoming: IncomingMessage, now_utc: datetime | None = None) -> Outcome:
    """Answer the message, or leave it to the thread that is answering its chat right now.

    Returns the message's outcome when this thread answered it, Outcome(skipped="queued") when it waits in the chat's
    queue (the caller's thread is free at once), Outcome(skipped="flood") when MAX_QUEUED are waiting already: that
    message is not read, staff are told once. A thread that has been at one message for STUCK_AFTER no longer holds
    the chat: the next message takes the queue over, as late and out of order beats never."""
    key = (business_id, incoming.channel, incoming.chat_id)
    mine = (incoming, now_utc)
    with _queues_guard:
        queue = _queues.get(key)
        answering = queue is not None and time.monotonic() - queue.since < STUCK_AFTER
        if answering and len(queue.waiting) >= MAX_QUEUED:
            queue.dropped += 1
            first_dropped = queue.dropped == 1
        elif answering:
            queue.waiting.append(mine)
            return Outcome(skipped="queued")
        else:
            if queue is not None:
                log.error("A %s message of business %s has been in work for over %.0f s: its chat goes on without it",
                          incoming.channel, business_id, STUCK_AFTER)
            queue = _Queue(queue.waiting if queue is not None else deque())  # what waited behind the stuck one comes first
            queue.waiting.append(mine)
            _queues[key] = queue
            first_dropped = None
    if first_dropped is not None:
        if first_dropped:
            _tell_staff_of_flood(rt, business_id, incoming)
        return Outcome(skipped="flood")

    outcome = Outcome(skipped="queued")  # until this thread gets to its own message
    while True:
        with _queues_guard:
            if _queues.get(key) is not queue:  # this thread was stuck and the chat went on without it
                break
            if not queue.waiting:
                del _queues[key]
                if queue.dropped:
                    log.warning("%d %s message(s) of business %s were not read: over %d waited in one chat",
                                queue.dropped, incoming.channel, business_id, MAX_QUEUED)
                break
            item = queue.waiting.popleft()
            queue.since = time.monotonic()
        try:
            result = _answer(rt, business_id, *item)
        except Exception:  # the queue goes on: one message that broke must not leave the chat unanswered for good
            log.exception("Failed to process a %s message of business %s", incoming.channel, business_id)
            result = Outcome(skipped="error")
        if item is mine:
            outcome = result
    return outcome


def _tell_staff_of_flood(rt: Runtime, business_id: int, incoming: IncomingMessage) -> None:
    try:
        with new_session() as session:
            business = session.get(Business, business_id)
        if business is not None:
            who = incoming.user_name or incoming.chat_id
            notify_admins(rt, business, [
                f"В чат {CHANNEL_NAMES.get(incoming.channel, incoming.channel)} «{who}» приходит слишком много сообщений "
                f"подряд: больше {MAX_QUEUED} ждут ответа, следующие ИИ не читает, пока очередь не разберётся. "
                "Если это спам — заблокируйте чат: «Диалоги» → этот чат → «В чёрный список»."])
    except Exception:
        log.exception("Could not tell staff of business %s about a flood of messages", business_id)


def _answer(rt: Runtime, business_id: int, incoming: IncomingMessage, now_utc: datetime | None = None) -> Outcome:
    # The chat's turn starts before a voice message is recognised (the text sent right after it must not be answered
    # first) and lasts until the reply is sent: two messages in a row are answered in that order, not the second
    # reply first because the first one's send was slower.
    with chat_turn(business_id, incoming.channel, incoming.chat_id):
        if incoming.kind == "media" and incoming.media_ref:  # a voice message: recognise it before the engine sees it
            with new_session() as session:
                found = session.get(Business, business_id)
                # Recognition costs money: not for a duplicate webhook delivery, a switched-off bot or a lapsed subscription.
                worth = found is not None and found.bot_enabled and access_ok(session, found.id, now_utc or utcnow()) \
                    and not (incoming.external_id and already_seen(session, found.id, incoming.external_id)) \
                    and not blocked(session, found.id, incoming.channel, incoming.chat_id)
            if worth:
                incoming = voice.prepare(rt, found, incoming)
        with new_session() as session:
            business = session.get(Business, business_id)
            if business is None:
                return Outcome(skipped="unknown_business")
            try:
                outcome = handle_incoming(session, business, incoming, rt.get_llm, now_utc,
                                          base_url=rt.settings.public_base_url, get_altegio=rt.altegio)
                session.commit()
            except Exception:
                session.rollback()
                log.exception("Failed to process a %s message for %s", incoming.channel, business.slug)
                return Outcome(skipped="error")
        send_reply(rt, business, incoming.channel, incoming.chat_id, outcome, reply_to=incoming.reply_to,
                   who=incoming.user_name or incoming.chat_id)
    after_reply(rt, business, outcome)
    return outcome


def send_reply(rt: Runtime, business: Business, channel: str, chat_id: str, outcome: Outcome, reply_to: str = "",
               who: str = "") -> None:
    """The customer's reply: the only send that has to keep the chat's order, so the only one inside its turn."""
    if not outcome.reply:
        return
    client = rt.channel_client(business, channel)
    if client is None:
        log.warning("No %s credentials for %s; reply not sent", channel, business.slug)
    elif reply_to and channel == "instagram":  # a comment: Direct opens through the comment, then a public pointer under it
        # The private reply fails when the permission is missing, the person closed message requests, or the comment is
        # older than seven days; a person who wrote to Direct before can still be reached by id. Otherwise staff answer.
        if client.send_private_reply(reply_to, outcome.reply) or client.send_text(chat_id, outcome.reply):
            if business.ig_comment_public_reply.strip():
                client.reply_to_comment(reply_to, business.ig_comment_public_reply.strip())
        else:
            log.warning("Instagram comment reply for %s was not delivered", business.slug)
            outcome.admin_notes.append(f"Не удалось ответить в Директ на комментарий в Instagram от {who or chat_id}: "
                                       f"«{outcome.reply[:120]}» — ответьте под ним сами.")
    elif not client.send_text(chat_id, outcome.reply):
        log.warning("Reply to %s via %s was not delivered", business.slug, channel)


def after_reply(rt: Runtime, business: Business, outcome: Outcome) -> None:
    """Notes to staff and offers to the waiting list. Each is a send of up to 20 seconds to somebody else's chat:
    outside the customer's turn, so the customer's next message is not kept waiting for them."""
    if outcome.admin_notes:
        notify_admins(rt, business, outcome.admin_notes)
    offer_freed(rt, business, outcome.freed_slot_ids)


def deliver(rt: Runtime, business: Business, channel: str, chat_id: str, outcome: Outcome, reply_to: str = "", who: str = "") -> None:
    send_reply(rt, business, channel, chat_id, outcome, reply_to=reply_to, who=who)
    after_reply(rt, business, outcome)


def offer_freed(rt: Runtime, business: Business, slot_ids: list[int]) -> None:
    """Times a customer gave back in a chat (joop/selfservice.py) go to the waiting list. Every chat that calls
    handle_incoming itself (the site chat, the panel's test chat) calls this too, not only deliver()."""
    if not slot_ids:
        return
    from . import waitlist
    from .models import Slot

    with new_session() as session:
        found = session.get(Business, business.id)
        for slot_id in slot_ids:
            slot = session.get(Slot, slot_id)
            if found is not None and slot is not None:
                waitlist.offer_freed_slot(session, rt, found, slot, utcnow())
        session.commit()


def admin_link(business: Business) -> str:
    """One tap from the panel: Telegram opens the business's bot with /start admin_<code>, and that chat gets the alerts."""
    if not (business.telegram_bot_token and business.telegram_bot_username and business.admin_link_code):
        return ""
    return f"https://t.me/{business.telegram_bot_username}?start=admin_{business.admin_link_code}"


def admin_chat_ids(business: Business) -> list[str]:
    return [x.strip() for x in (business.admin_chat_ids or "").split(",") if x.strip()]


def alert_chats(business: Business) -> list[str]:
    """The linked chats that actually get the alerts. Alerts go through the business's own bot (notify_admins), so with
    the bot disconnected none arrive: the chats stay linked for a reconnect, but the panel must not count them. Nor
    after the owner connected another bot: Telegram lets a bot write only to chats that started it or added it, so the
    chats linked through the previous bot have to be linked again (/admin to the new bot)."""
    if not business.telegram_bot_token:
        return []
    if business.admin_bot and business.admin_bot != bot_id(business.telegram_bot_token):
        return []
    return admin_chat_ids(business)


def alerts_other_bot(business: Business) -> bool:
    """Chats are linked, but through a bot that is no longer the business's: the settings say to link them again."""
    return bool(admin_chat_ids(business) and business.telegram_bot_token and business.admin_bot
                and business.admin_bot != bot_id(business.telegram_bot_token))


def notify_admins(rt: Runtime, business: Business, notes: list[str], session: Session | None = None) -> int:
    """Send notes to every linked admin chat through the business's Telegram bot. Returns messages sent.
    `session`: the caller's, when it may hold changes — they are stored before Telegram is asked (db.free)."""
    telegram = rt.telegram(business)
    chats = alert_chats(business)  # not the chats of a previous bot: this one cannot write there
    if telegram is None or not chats:
        log.info("Admin notifications for %s are not set up; %d note(s) kept only in the panel", business.slug, len(notes))
        return 0
    if session is not None and notes:
        free(session)
    sent = 0
    for note in notes:
        for chat_id in chats:
            if telegram.send_text(chat_id, note):
                sent += 1
    return sent
