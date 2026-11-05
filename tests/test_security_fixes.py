"""Security review of PRs #96–#109: tokens out of logs, the audit upload off the event loop and linear, counters that cannot
be inflated, one comment opening per commenter a day, a lead cooldown that survives a dropped cookie."""

import logging
import time

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import audit, db
from joop.models import Business, SignatureClick
from joop.web import app as web_app
from joop.web.app import create_app

from .test_ig_comments import _comment
from .test_web import _signed, client, csrf_of  # noqa: F401  (fixture)


def test_httpx_request_lines_are_silenced_so_bot_tokens_stay_out_of_logs(monkeypatch):
    from joop.__main__ import main

    monkeypatch.setattr("sys.argv", ["joop", "--help"])
    try:
        main()
    except SystemExit:
        pass
    assert logging.getLogger("httpx").level >= logging.WARNING and logging.getLogger("httpcore").level >= logging.WARNING


def test_audit_parse_is_linear_in_continuation_lines():
    text = "04.11.2026, 11:00 - Клиент: Привет\n" + "ab\n" * 200_000
    started = time.perf_counter()
    [msg] = audit.parse(text)
    assert time.perf_counter() - started < 3 and msg.text.count("\nab") == 200_000


def test_audit_refuses_a_body_larger_than_the_cap(client):
    token = csrf_of(client.get("/audit").text)
    r = client.post("/audit", data={"csrf": token}, headers={"content-length": str(audit.MAX_FILES * audit.MAX_BYTES + 1)})
    assert r.status_code == 413


def test_signature_clicks_count_once_per_browser_a_day_and_not_crawlers(business, rt, settings):
    web_app._daily.clear()
    with TestClient(create_app(settings, rt, init=False)) as c:
        for _ in range(3):
            c.get("/ai/aktish", follow_redirects=False)  # the same browser: one click
        c.get("/ai/aktish", follow_redirects=False, headers={"user-agent": "TelegramBot (like TwitterBot)"})
    with TestClient(create_app(settings, rt, init=False)) as c:
        c.get("/ai/aktish", follow_redirects=False, headers={"user-agent": "WhatsApp/2.23.20.0"})  # a link preview: not a person
    with db.new_session() as s:
        assert len(s.exec(select(SignatureClick)).all()) == 1
    for _ in range(web_app.SIGNATURE_PER_ADDRESS + 5):  # fresh browsers from one address: capped
        with TestClient(create_app(settings, rt, init=False)) as c:
            c.get("/ai/aktish", follow_redirects=False)
    with db.new_session() as s:
        assert len(s.exec(select(SignatureClick)).all()) == web_app.SIGNATURE_PER_ADDRESS


def test_one_direct_opening_per_commenter_a_day(client, rt, business):
    web_app._daily.clear()
    with db.new_session() as s:
        b = s.get(Business, business.id)
        b.ig_account_id, b.ig_access_token, b.ig_comments = "ig-1", "tok", True
        s.commit()
    for n in range(4):
        raw, headers = _signed(_comment(f"Сколько стоит? {n}", cid=f"c-spam-{n}"))
        client.post("/webhooks/meta", content=raw, headers=headers)
    assert len(rt.ig.private) == 1 and len(rt.ig.public) == 1
    raw, headers = _signed(_comment("А у вас есть окно?", cid="c-other", sender="igsid-8", username="other"))
    client.post("/webhooks/meta", content=raw, headers=headers)
    assert len(rt.ig.private) == 2  # another person is not throttled by the first


def test_audit_lead_cooldown_holds_without_the_cookie(client):
    from joop.web import audit as web_audit

    web_audit._lead_by_ip.clear()
    sample = "04.11.2026, 11:00 - Клиент: Сколько стоит?\n04.11.2026, 11:10 - Салон: 800 сом\n"
    tokens = []
    for _ in range(2):
        token = csrf_of(client.get("/audit").text)
        page = client.post("/audit", data={"csrf": token, "work_start": "10:00", "work_end": "20:00"},
                           files=[("chats", ("chat.txt", sample.encode(), "text/plain"))]).text
        tokens.append(page.split('name="token" value="')[1].split('"')[0])
    token = csrf_of(client.get("/audit").text)
    data = {"csrf": token, "business": "Салон", "phone": "+996555000111", "niche": "beauty"}
    r1 = client.post("/audit/lead", data={**data, "token": tokens[0]})
    assert "Спасибо" in r1.text
    client.cookies.clear()  # a new cookie jar: the session cooldown is gone, the address cooldown is not
    token = csrf_of(client.get("/audit").text)
    r2 = client.post("/audit/lead", data={**data, "csrf": token, "token": tokens[1]})
    assert "Спасибо" not in r2.text
