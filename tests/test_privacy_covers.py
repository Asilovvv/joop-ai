"""The privacy page lists every place where the service collects people's data."""

from fastapi.testclient import TestClient

from joop.web.app import create_app


def test_privacy_names_the_booking_page_staff_entries_and_sign_up(settings, rt, engine):
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/privacy").text
    assert "страницы записи клиента" in page and "Напомнить в Telegram" in page  # /m/<slug>/book, #255 and #258
    assert "вносят в панель сами" in page  # bookings by phone, stays, memberships, job orders
    assert "только в виде хеша" in page and "имя и телефон из регистрации" in page
    assert "которым мы сами предлагаем сервис" in page  # the founder's prospects list
    assert "не храним номера карт, пароли от мессенджеров" in page


def test_privacy_names_what_the_review_found_missing(settings, rt, engine):
    """Review of #263: missed calls, delivery addresses, staff notes, the business's own API and webhooks, partners;
    and «не используем для рекламы» beside broadcasts and invitations the service sends for the business."""
    with TestClient(create_app(settings, rt, init=False)) as c:
        page = c.get("/privacy").text
    assert "позвонили клиенту и не дозвонились" in page and "пишет позвонившему туда" in page  # joop/missed_calls.py
    assert "адрес доставки" in page and "оценка визита" in page  # Order.address, Booking.rating
    assert "свои заметки и метки" in page  # Customer.note and tags, ConversationNote
    assert "ключ API или указал адрес для уведомлений (вебхук)" in page  # joop/api.py
    assert "Партнёры, которые рекомендуют сервис" in page  # Partner
    assert "приглашение прийти снова или повторить заказ" in page and "Слово «отписаться» в чате прекращает" in page
    assert "не используем их для собственной рекламы" in page and "не используем их для рекламы" not in page
    assert "резервная копия" not in page  # no copy leaves this server: nothing to say


def test_privacy_mentions_the_offsite_copy_only_when_it_is_made(settings, rt, engine, monkeypatch):
    import dataclasses

    from joop import crypto

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", crypto.new_key())
    on = dataclasses.replace(settings, founder_bot_token="1:a", founder_chat_id="42")
    with TestClient(create_app(on, rt, init=False)) as c:
        assert "резервная копия базы хранится вне сервера, в Telegram оператора сервиса, только в зашифрованном виде" in c.get("/privacy").text
    with TestClient(create_app(dataclasses.replace(on, backup_to_telegram=False), rt, init=False)) as c:
        assert "резервная копия" not in c.get("/privacy").text
