"""«Подключить Instagram» in one click (joop/ig_login.py and its two routes in joop/web/app.py).

Before it, the owner had to find the account's Instagram ID and generate a token in Meta's developer dashboard and
paste both: no small business does that on its own.
"""

import dataclasses
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from joop import db
from joop.models import Business
from joop.web.app import create_app

from .test_web import csrf_of, login


class Instagram:
    """Instagram's three endpoints, answering as configured; records what the server asked."""

    def __init__(self, **over):
        self.calls: list[tuple[str, str, dict]] = []
        self.answers = {
            "code": (200, {"data": [{"access_token": "short-token", "user_id": "987", "permissions": "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments"}]}),
            "long": (200, {"access_token": "long-token", "token_type": "bearer", "expires_in": 5183944}),
            "me": (200, {"user_id": "17841400000000001", "username": "aktish.dent", "account_type": "BUSINESS", "id": "987"}),
            "subscribe": (200, {"success": True}),
        }
        self.answers.update(over)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://api.instagram.com/oauth/access_token"):
            key, sent = "code", parse_qs(request.content.decode())
        elif "/access_token?" in url:
            key, sent = "long", parse_qs(urlsplit(url).query)
        elif url.split("?")[0].endswith("/me/subscribed_apps"):
            key, sent = "subscribe", parse_qs(urlsplit(url).query)
        elif url.split("?")[0].endswith("/me"):
            key, sent = "me", parse_qs(urlsplit(url).query)
        else:
            return httpx.Response(404, json={"error": {"message": "unexpected " + url}})
        sent = {k: v[0] for k, v in sent.items()}
        sent["auth"] = request.headers.get("authorization", "")
        self.calls.append((key, request.method, sent))
        status, body = self.answers[key]
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)


@pytest.fixture
def ig_settings(settings):
    return dataclasses.replace(settings, instagram_app_id="111222333", instagram_app_secret="ig-secret")


def start(client) -> str:
    """Press «Подключить Instagram»; returns the `state` sent to Instagram."""
    token = login(client)
    page = client.get("/panel/channels").text
    assert "Подключить Instagram" in page
    r = client.post("/panel/channels/instagram", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    url = urlsplit(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://www.instagram.com/oauth/authorize"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["client_id"] == "111222333" and q["response_type"] == "code"
    assert q["redirect_uri"] == "https://joop.test/panel/channels/instagram/callback"
    assert set(q["scope"].split(",")) == {"instagram_business_basic", "instagram_business_manage_messages", "instagram_business_manage_comments"}
    return q["state"]


def app_with(ig_settings, rt, ig: Instagram):
    rt.http = httpx.Client(transport=httpx.MockTransport(ig.handler))
    return TestClient(create_app(ig_settings, rt, init=False))


def saved(business_id):
    with db.new_session() as s:
        return s.get(Business, business_id)


def test_one_click_connects_the_account(ig_settings, rt, business):
    ig = Instagram()
    with app_with(ig_settings, rt, ig) as c:
        state = start(c)
        r = c.get(f"/panel/channels/instagram/callback?code=the-code%23_&state={state}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/panel/channels"
        page = c.get("/panel/channels").text
    assert "Instagram @aktish.dent подключён" in page and "Подключить другой аккаунт" in page
    b = saved(business.id)
    assert (b.ig_account_id, b.ig_access_token, b.ig_username) == ("17841400000000001", "long-token", "aktish.dent")
    assert b.ig_token_refreshed_at is not None
    code, long, me, sub = ig.calls
    assert code[1] == "POST" and code[2]["code"] == "the-code" and code[2]["client_secret"] == "ig-secret"  # «#_» is not the code
    assert code[2]["redirect_uri"] == "https://joop.test/panel/channels/instagram/callback"
    assert long[2] == {"grant_type": "ig_exchange_token", "client_secret": "ig-secret", "access_token": "short-token", "auth": ""}
    assert me[2]["auth"] == "Bearer long-token" and "user_id" in me[2]["fields"]
    assert sub[1] == "POST" and sub[2]["subscribed_fields"] == "messages,message_echoes,comments"


def test_nothing_is_saved_when_a_step_fails(ig_settings, rt, business):
    for over, words in (
        ({"code": (400, {"error_type": "OAuthException", "error_message": "Matching code was not found or was already used"})}, "Instagram отказал"),
        ({"me": (200, {"user_id": "5", "username": "me", "account_type": "PERSONAL"})}, "личный аккаунт"),
        ({"subscribe": (400, {"error": {"message": "Unsupported request"}})}, "Instagram отказал (подписка на сообщения)"),
        ({"code": (200, {"data": [{"access_token": "t", "user_id": "1", "permissions": "instagram_business_basic"}]})}, "Без разрешения на сообщения"),
        ({"long": (200, httpx.ConnectError("down"))}, "Instagram не ответил"),
    ):
        with app_with(ig_settings, rt, Instagram(**over)) as c:
            state = start(c)
            page = c.get(f"/panel/channels/instagram/callback?code=c&state={state}").text  # back on «Каналы», with the message
        assert words in page, words
        b = saved(business.id)
        assert b.ig_account_id == "" and b.ig_access_token == "", words


def test_a_callback_without_our_state_is_refused(ig_settings, rt, business):
    ig = Instagram()
    with app_with(ig_settings, rt, ig) as c:
        start(c)
        assert "Ссылка устарела" in c.get("/panel/channels/instagram/callback?code=c&state=forged").text
        state = start(c)
        c.get(f"/panel/channels/instagram/callback?code=c&state={state}")
        again = c.get(f"/panel/channels/instagram/callback?code=c&state={state}").text  # the same link again: the state was used up
        assert "Ссылка устарела" in again
    assert len([call for call in ig.calls if call[0] == "code"]) == 1


def test_cancelling_at_instagram_says_so(ig_settings, rt, business):
    ig = Instagram()
    with app_with(ig_settings, rt, ig) as c:
        state = start(c)
        page = c.get(f"/panel/channels/instagram/callback?error=access_denied&error_reason=user_denied&state={state}").text
        assert "Подключение Instagram отменено." in page
    assert ig.calls == []


def test_an_account_of_another_company_is_not_taken(ig_settings, rt, business):
    with db.new_session() as s:
        other = Business(slug="other", name="Другая клиника", password_hash="x", ig_account_id="17841400000000001", ig_access_token="t")
        s.add(other)
        s.commit()
    with app_with(ig_settings, rt, Instagram()) as c:
        state = start(c)
        assert "уже подключён к другой компании" in c.get(f"/panel/channels/instagram/callback?code=c&state={state}").text
    assert saved(business.id).ig_account_id == ""


def test_no_button_until_the_server_can_finish(settings, rt, business):
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = login(c)
        assert "Подключить Instagram" not in c.get("/panel/channels").text
        assert "ещё не настроено на сервере" in c.post("/panel/channels/instagram", data={"csrf": token}).text


def test_staff_logins_cannot_connect_channels(ig_settings, rt, business):
    with TestClient(create_app(ig_settings, rt, init=False)) as c:
        r = c.get("/panel/channels/instagram/callback?code=c&state=s", follow_redirects=False)
        assert r.status_code in (302, 303) and "/login" in r.headers["location"]
