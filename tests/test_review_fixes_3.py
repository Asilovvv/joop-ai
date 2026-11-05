"""Third independent review (PRs #96–#101): what it found, fixed and pinned down.

1. Release of unconfirmed bookings: silence since the question, not «the question is the AI's last word».
2. The business's own Instagram comments (the pointer Joop posts, the owner's replies) are never questions.
3. «Ок, а сколько стоит?» is a question, not a closing «ок» — in the follow-up and in the audit.
4. The counter card points only at channels where Joop answers; disconnecting Telegram clears the username.
5. A failed private reply falls back to Direct by id, else staff get a note.
6. The playbook names its sources and no longer derives the founder's name from the legal name.
7. «Да да, буду обязательно» confirms; release hours stored above the cap count as the cap.
8. Keywords match at the start of a word; «Записалась, спасибо!» opens no Direct thread.
"""

from datetime import datetime, timedelta

import httpx
from fastapi.testclient import TestClient
from sqlmodel import select

from joop import audit, confirm, db, ig_comments, unfinished
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.channels.meta import InstagramClient
from joop.dispatch import deliver
from joop.models import Booking, Business, Conversation, Message, Slot, Staff
from joop.web.app import create_app

from .conftest import FakeLLM
from .test_ig_comments import _comment
from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)
from .test_scheduler import EVENING_UTC, _book, _run
from .test_web import _signed, client, csrf_of, login  # noqa: F401  (fixture)


def _second_booking(business, chat="1001", at=datetime(2026, 11, 5, 11, 0)):
    with db.new_session() as s:
        b = s.get(Business, business.id)
        slot = s.exec(select(Slot).join(Staff).where(Slot.business_id == b.id, Slot.status == "free", Slot.start == at)).first()
        llm = FakeLLM([AgentReply("Записала", booking={"slot_id": slot.id, "name": "Айбек", "phone": "0555123456", "service": "чистка"})])
        handle_incoming(s, b, IncomingMessage("telegram", chat, "text", "и ещё на 11", "", f"tg:{chat}:second"), lambda: llm, EVENING_UTC - timedelta(minutes=5))
        s.commit()


def test_release_frees_the_second_visit_of_a_chat_after_the_first(business, rt):
    """Finding 1: after one release the AI has spoken again, but the silence on the other booking is still silence."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.release_unconfirmed_hours, b.admin_chat_ids = 3, "999"
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")  # 10:00
    _second_booking(business)  # 11:00, same chat
    assert _run(business, rt)["reminders"]["sent"] == 2
    assert _run(business, rt, datetime(2026, 11, 5, 1, 0))["unconfirmed"] == {"released": 1}  # 07:00: the 10:00 visit
    assert _run(business, rt, datetime(2026, 11, 5, 2, 1))["unconfirmed"] == {"released": 1}  # 08:01: the 11:00 visit too
    with db.new_session() as s:
        rows = s.exec(select(Booking).where(Booking.channel == "telegram").order_by(Booking.start)).all()
        assert [b.status for b in rows] == ["cancelled", "cancelled"]
    assert sum(1 for chat, t in rt.tg.sent if chat == "1001" and "время освобождено" in t) == 2
    assert "unconfirmed" not in _run(business, rt, datetime(2026, 11, 5, 2, 30))  # nothing left


def test_release_spares_a_customer_who_wrote_back_without_a_yes(business, rt):
    """The customer answered the question with something else: the model handled it, nobody is blamed for silence."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.release_unconfirmed_hours = 3
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    _run(business, rt)
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "1001", "text", "А где вы находитесь?", "Айбек", "tg:1001:where"),
                        lambda: FakeLLM([AgentReply("Чуй 100.")]), EVENING_UTC + timedelta(minutes=30))
        s.commit()
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "1001")).one()
        assert confirm.silent_since_ask(s, conv) is None and confirm.asked_at(s, conv) is None
    assert "unconfirmed" not in _run(business, rt, datetime(2026, 11, 5, 1, 0))
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.channel == "telegram")).one().status == "booked"


def test_a_longer_yes_still_confirms_and_stored_hours_above_the_cap_count_as_the_cap(business, rt, settings):
    """Finding 7."""
    assert confirm.says_yes("Да да, буду обязательно") and confirm.says_yes("Ооба, сөзсүз келем")
    assert not confirm.says_yes("Да, в 10 буду") and not confirm.says_yes("да да да буду обязательно точно")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.release_unconfirmed_hours = 24  # saved before the cap went from 24 to 12
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    assert _run(business, rt)["reminders"]["sent"] == 1
    assert "unconfirmed" not in _run(business, rt, EVENING_UTC + timedelta(hours=3))  # 21:05: 13 h before 10:00 — not yet with the cap
    assert _run(business, rt, EVENING_UTC + timedelta(hours=4))["unconfirmed"] == {"released": 1}  # 22:05: within 12 h
    with TestClient(create_app(settings, rt, init=False)) as c:
        login(c)
        page = c.get("/panel/settings").text
        assert 'name="release_unconfirmed_hours" value="12"' in page  # the form submits again
        token = csrf_of(page)
        c.post("/panel/settings", data={"csrf": token, "release_unconfirmed_hours": "12", "deposit_amount": "0", "deposit_hours": "2", "deposit_details": ""})
        with db.new_session() as s:
            assert s.get(Business, business.id).release_unconfirmed_hours == 12


def test_own_comments_and_the_pointer_are_not_questions(client, rt, business):
    """Finding 2: the pointer Joop posts and the owner's own replies never come back as customer questions."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token, b.ig_comments, b.ig_username = "ig-1", "tok", True, "Aktish_Dent"
        s.commit()
    for body in (_comment("Ответили вам в Директ", cid="c-own-1", sender="igsid-biz", username="someone"),  # the pointer, whoever posts it
                 _comment("Цена 1500, запись в Директ", cid="c-own-2", sender="igsid-biz", username="aktish_dent"),  # the owner's reply
                 _comment("Сколько стоит?", cid="c-own-3", sender="igsid-biz", username="aktish_dent")):
        raw, headers = _signed(body)
        client.post("/webhooks/meta", content=raw, headers=headers)
    assert rt.ig.private == [] and rt.ig.public == []
    with db.new_session() as s:
        assert s.exec(select(Conversation).where(Conversation.business_id == business.id)).all() == []
    raw, headers = _signed(_comment("Сколько стоит?", cid="c-4"))  # a customer, as before
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert [cid for cid, _ in rt.ig.private] == ["c-4"]


def test_instagram_me_and_the_channels_page_remember_the_username(business, rt, settings):
    seen = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={"id": "ig-1", "username": "aktish_dent"})))
    me = InstagramClient(http, "https://graph.instagram.test", "v26.0", "ig-1", "tok").get_me()
    assert me["username"] == "aktish_dent" and seen[0].url.path == "/v26.0/me" and "username" in seen[0].url.params["fields"]
    broken = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"message": "bad token"}})))
    assert InstagramClient(broken, "https://graph.instagram.test", "v26.0", "ig-1", "tok").get_me() == {}

    import dataclasses

    rt.settings = dataclasses.replace(settings, meta_verify_token="v", meta_app_secret="s")
    rt.ig.me = {"id": "ig-1", "username": "aktish_dent"}
    with TestClient(create_app(rt.settings, rt, init=False)) as c:
        login(c)
        token = csrf_of(c.get("/panel/channels").text)
        c.post("/panel/channels", data={"csrf": token, "ig_account_id": "ig-1", "ig_access_token": "tok", "ig_comments": "1"})
        with db.new_session() as s:
            assert s.get(Business, business.id).ig_username == "aktish_dent"
        c.post("/panel/channels", data={"csrf": token, "ig_account_id": "", "clear_ig_access_token": "1"})
        with db.new_session() as s:
            assert s.get(Business, business.id).ig_username == ""  # disconnected: nothing to match against


def test_keywords_match_whole_words_and_thanks_open_no_thread():
    """Finding 8."""
    b = Business(slug="x", name="X", ig_comments=True)
    assert ig_comments.wanted(b, "Цена?") and ig_comments.wanted(b, "цена") and ig_comments.wanted(b, "Запишите меня на завтра")
    assert ig_comments.wanted(b, "Сколько стоит") and ig_comments.wanted(b, "есть окно в субботу")
    assert not ig_comments.wanted(b, "Не стоит благодарности") and not ig_comments.wanted(b, "Записалась, спасибо!")
    assert not ig_comments.wanted(b, "Спасибо, запись прошла отлично") and not ig_comments.wanted(b, "Красота! Обожаю")
    assert ig_comments.wanted(b, "Спасибо! А запись на завтра есть?")  # a question after thanks is still a question
    assert ig_comments.own(b, "Ответили вам в Директ", "anyone") and not ig_comments.own(b, "Ответили вам в Директ!", "anyone")
    b.ig_username = "x_salon"
    assert ig_comments.own(b, "Спасибо всем!", "X_Salon") and not ig_comments.own(b, "Спасибо всем!", "x_salon_fan")


def test_closing_words_do_not_hide_a_question():
    """Finding 3."""
    for text in ("Спасибо!", "Ок, понятно", "Хорошо, до встречи", "Рахмат", "👍", "Ладно"):
        assert unfinished.closing(text), text
    for text in ("Ок, а сколько стоит?", "Спасибо! А на завтра можно записаться?", "Хорошо, запишите меня на 10:00", "Спасибо, а адрес какой", ""):
        assert not unfinished.closing(text), text
    chat = audit.parse("04.11.2026, 11:00 - Клиент: Привет\n04.11.2026, 11:10 - Салон: Здравствуйте!\n04.11.2026, 11:12 - Клиент: Спасибо, а сколько стоит маникюр?\n")
    r = audit.report([chat], "Салон", "10:00", "20:00")
    assert r.unanswered == 1 and r.price_questions == 1


def test_follow_up_goes_to_ok_but_how_much(business, rt):
    """Finding 3 in the follow-up: «Ок, а сколько стоит?» that went quiet gets the two nearest times."""
    from joop.scheduler import run_due_jobs
    from .test_unfinished import ASKED_UTC, LATER, _turn_on

    _turn_on(business.id)
    with db.new_session() as s:
        handle_incoming(s, s.get(Business, business.id), IncomingMessage("telegram", "1001", "text", "Ок, а сколько стоит чистка?", "Айбек", "tg:1001:q"),
                        lambda: FakeLLM([AgentReply("3 000 сом.")]), ASKED_UTC)
        s.commit()
    with db.new_session() as s:
        report = run_due_jobs(s, rt, s.get(Business, business.id), LATER)
        s.commit()
    assert report["unfinished"] == {"sent": 1}


def test_card_offers_only_channels_where_joop_answers(business, rt, settings):
    """Finding 4: no WhatsApp link to a landline, no Telegram link to a disconnected bot; an old connection learns its username."""
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.phone, b.telegram_bot_username = "+996 555 000 111", ""  # Telegram connected before the username was kept
        s.add(b)
        s.commit()
    rt.tg.me = {"username": "aktish_bot"}
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        page = c.get("/panel/card?via=whatsapp").text
        assert "wa.me" not in page and "WhatsApp ещё не подключён" in page and "https://t.me/aktish_bot" in page
        with db.new_session() as s:
            assert s.get(Business, business.id).telegram_bot_username == "aktish_bot"
        with db.new_session() as s:
            b = s.get(Business, business.id)
            b.wa_phone_number_id, b.wa_access_token = "pn1", "tok"
            s.add(b)
            s.commit()
        assert "https://wa.me/996555000111" in c.get("/panel/card?via=whatsapp").text
        rt.tg.delete_webhook = lambda: True
        c.post("/panel/channels/telegram/disconnect", data={"csrf": token})
        with db.new_session() as s:
            b = s.get(Business, business.id)
            assert b.telegram_bot_token == "" and b.telegram_bot_username == ""
        page = c.get("/panel/card?via=telegram").text
        assert "t.me/" not in page and "Telegram-бот ещё не подключён" in page


def test_private_reply_falls_back_to_direct_by_id_or_tells_staff(business, rt):
    """Finding 5."""
    from joop.agent.engine import Outcome

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token, b.admin_chat_ids = "ig-1", "tok", "999"
        s.add(b)
        s.commit()
        b = s.get(Business, business.id)
    calls = []

    def private(comment_id, text):
        calls.append(("private", comment_id))
        return False

    rt.ig.send_private_reply = private
    deliver(rt, b, "instagram", "igsid-7", Outcome(reply="Маникюр — 800 сом."), reply_to="c-1")
    assert rt.ig.sent == [("igsid-7", "Маникюр — 800 сом.")] and rt.ig.public == [("c-1", "Ответили вам в Директ")]
    assert not [t for chat, t in rt.tg.sent if chat == "999"]
    rt.ig.ok = False  # Direct by id fails too: the public pointer is not posted, staff hear about it
    out = Outcome(reply="Маникюр — 800 сом.")
    deliver(rt, b, "instagram", "igsid-7", out, reply_to="c-2")
    assert rt.ig.public == [("c-1", "Ответили вам в Директ")]
    assert out.admin_notes == ["Не удалось ответить в Директ на комментарий в Instagram от igsid-7: «Маникюр — 800 сом.» — ответьте под ним сами."]
    assert ("999", out.admin_notes[0]) in rt.tg.sent


def test_playbook_names_its_sources(app_client):
    """Finding 6: the figures are other people's and say so; the founder's name is not cut out of the legal name."""
    owner_login(app_client)
    page = app_client.get("/owner/playbook").text
    assert "Откуда цифры" in page and "docs/sales-sources.md" in page and "forbes.kz" in page
    assert "это Бектур из Joop" in page and "ИП из Joop" not in page
    assert "20–25 живых" not in page and "В тесте сервисной компании" not in page


# --- fourth review (PRs #102–#106) ---------------------------------------------------------------------


def test_staff_taking_the_chat_over_stops_the_release_and_a_yes_with_mozhno_confirms(business, rt):
    """Findings 4 and 7."""
    assert confirm.says_yes("Да, можно") and confirm.says_yes("Ооба, болот") and confirm.says_yes("Да, непременно")
    assert not confirm.says_yes("Да, а можно позже") and not confirm.says_yes("да а сколько стоит") and not confirm.says_yes("можно")
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.release_unconfirmed_hours = 3
        s.add(b)
        s.commit()
    _book(business, "telegram", "1001")
    _run(business, rt)
    with db.new_session() as s:
        conv = s.exec(select(Conversation).where(Conversation.chat_id == "1001")).one()
        s.add(Message(business_id=business.id, conversation_id=conv.id, role="staff", text="Ждём вас завтра, подтвердили по телефону",
                      created_at=EVENING_UTC + timedelta(minutes=30)))
        s.commit()
        assert confirm.silent_since_ask(s, conv) is None
    assert "unconfirmed" not in _run(business, rt, datetime(2026, 11, 5, 1, 0))
    with db.new_session() as s:
        assert s.exec(select(Booking).where(Booking.channel == "telegram")).one().status == "booked"


def test_thanks_with_a_request_after_it_still_opens_a_thread():
    """Finding 10."""
    b = Business(slug="x", name="X", ig_comments=True)
    assert ig_comments.wanted(b, "Спасибо, скажите цену") and ig_comments.wanted(b, "Записалась бы, есть окно на завтра")
    assert not ig_comments.wanted(b, "Записалась, спасибо!") and not ig_comments.wanted(b, "Спасибо большое")
    assert ig_comments.wanted(b, "цену скажите") and ig_comments.wanted(b, "Какие окна есть")


def test_failed_comment_reply_note_names_the_commenter_and_the_text(business, rt):
    """Finding 5."""
    from joop.agent.engine import Outcome

    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token, b.admin_chat_ids = "ig-1", "tok", "999"
        s.add(b)
        s.commit()
        b = s.get(Business, business.id)
    rt.ig.ok = False
    out = Outcome(reply="Маникюр — 800 сом.")
    deliver(rt, b, "instagram", "igsid-7", out, reply_to="c-2", who="aigerim_nails")
    assert out.admin_notes == ["Не удалось ответить в Директ на комментарий в Instagram от aigerim_nails: «Маникюр — 800 сом.» — ответьте под ним сами."]


def test_privacy_pages_promise_only_what_the_code_does(client):
    """Finding 9."""
    privacy = client.get("/privacy").text
    assert "по его запросу в течение 30 дней" in privacy and "удаляются в течение 30 дней" not in privacy
    deletion = client.get("/data-deletion").text
    assert "в чате на сайте" in deletion and "имя и телефон, которые вы написали в чате" in deletion
