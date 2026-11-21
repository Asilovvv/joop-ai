"""«Подключить Instagram» in one click: Business Login for Instagram instead of pasting an ID and a token.

The owner presses the button in «Каналы», logs in to Instagram and allows Joop to answer messages; Instagram sends
them back to /panel/channels/instagram/callback with a one-hour code. The server then
1. exchanges the code for a short-lived token, and that for a 60-day one (the scheduler refreshes it weekly);
2. asks /me for the account's Instagram ID (the `entry.id` of every webhook, how Joop finds the business) and
   its username (its own comments under its posts are not questions, joop/ig_comments.py);
3. subscribes the account to the app's webhook, which a Meta app does not do on its own.
Nothing is saved until all three worked: a half-connected account looks connected and answers nobody.

Needs INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET of the founder's Meta app, PUBLIC_BASE_URL, and the redirect address
registered in the app (docs/channels.md). Serving other businesses' customers needs Meta's App Review of
instagram_business_basic and instagram_business_manage_messages; before it, only accounts with a role on the app work.

Meta's documentation: developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/
business-login (checked 21 November 2026).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
CODE_URL = "https://api.instagram.com/oauth/access_token"
SCOPES = ("instagram_business_basic", "instagram_business_manage_messages", "instagram_business_manage_comments")
FIELDS = ("messages", "message_echoes", "comments")  # comments: questions under posts, when the business turns that on
CALLBACK_PATH = "/panel/channels/instagram/callback"


class LoginFailed(Exception):
    """Shown to the owner as it is: what went wrong, in Russian, and what to do."""


@dataclass
class Account:
    account_id: str
    username: str
    token: str


def ready(settings: Settings) -> bool:
    """The button is shown only when the server can finish what it starts."""
    return bool(settings.instagram_app_id and settings.instagram_app_secret and settings.meta_verify_token
                and settings.public_base_url.startswith("https://"))  # Instagram sends messages only to an https webhook


def redirect_uri(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/") + CALLBACK_PATH


def authorize_url(settings: Settings, state: str) -> str:
    query = {
        "client_id": settings.instagram_app_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
        "enable_fb_login": "false",  # the business account itself, not a Facebook profile
        "force_reauth": "true",  # the owner picks the account, not whichever is logged in on this computer
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _first(data: dict[str, Any]) -> dict[str, Any]:
    """Meta documents `{"data": [{…}]}` for some of these answers and returns the flat object for others."""
    rows = data.get("data")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return data


def _call(http: httpx.Client, method: str, url: str, what: str, **kw) -> dict[str, Any]:
    try:
        response = http.request(method, url, timeout=20.0, **kw)
    except httpx.HTTPError as exc:
        log.warning("Instagram login: %s failed: %s", what, type(exc).__name__)
        raise LoginFailed("Instagram не ответил. Попробуйте подключить ещё раз через минуту.") from None
    data = _json(response)
    if response.status_code >= 400:
        error = data.get("error")
        message = error.get("message") if isinstance(error, dict) else data.get("error_message") or error
        log.warning("Instagram login: %s failed: HTTP %s %s", what, response.status_code, str(message or "")[:200])
        raise LoginFailed(f"Instagram отказал ({what}). Попробуйте подключить ещё раз; если повторится — напишите нам.")
    return data


def connect(http: httpx.Client, settings: Settings, code: str) -> Account:
    """The account behind a code from the callback, subscribed to the webhook, with a 60-day token."""
    code = code.strip().removesuffix("#_")  # Instagram appends «#_», which is not part of the code
    short = _first(_call(http, "POST", CODE_URL, "обмен кода", data={
        "client_id": settings.instagram_app_id, "client_secret": settings.instagram_app_secret,
        "grant_type": "authorization_code", "redirect_uri": redirect_uri(settings), "code": code,
    }))
    granted = {p.strip() for p in str(short.get("permissions") or "").split(",") if p.strip()}
    if granted and "instagram_business_manage_messages" not in granted:
        raise LoginFailed("Без разрешения на сообщения ИИ не сможет отвечать в Директ. Подключите ещё раз и оставьте "
                          "включённым «Управление сообщениями».")
    if not short.get("access_token"):
        raise LoginFailed("Instagram не выдал доступ. Попробуйте подключить ещё раз.")
    base = settings.instagram_api_base.rstrip("/")
    long = _call(http, "GET", f"{base}/access_token", "долгий токен", params={
        "grant_type": "ig_exchange_token", "client_secret": settings.instagram_app_secret, "access_token": short["access_token"],
    })
    token = str(long.get("access_token") or "")
    if not token:
        raise LoginFailed("Instagram не выдал доступ. Попробуйте подключить ещё раз.")
    me = _first(_call(http, "GET", f"{base}/{settings.graph_api_version}/me", "данные аккаунта",
                      params={"fields": "user_id,username,account_type"}, headers={"Authorization": f"Bearer {token}"}))
    account_id = str(me.get("user_id") or "")
    if not account_id:
        raise LoginFailed("Instagram не сообщил ID аккаунта. Попробуйте подключить ещё раз.")
    if str(me.get("account_type") or "").upper() == "PERSONAL":
        raise LoginFailed("Это личный аккаунт. Переключите его на профессиональный (бизнес или автор) в настройках "
                          "Instagram и подключите ещё раз.")
    subscribed = _call(http, "POST", f"{base}/{settings.graph_api_version}/me/subscribed_apps", "подписка на сообщения",
                       params={"subscribed_fields": ",".join(FIELDS)}, headers={"Authorization": f"Bearer {token}"})
    if subscribed.get("success") is False:
        raise LoginFailed("Instagram не включил пересылку сообщений. Попробуйте подключить ещё раз.")
    return Account(account_id=account_id, username=str(me.get("username") or ""), token=token)
