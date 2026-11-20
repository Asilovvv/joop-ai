"""The outside check that the whole server answers (deploy/uptime.py, run by .github/workflows/uptime.yml)."""

import importlib.util
import io
import json
import ssl
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("uptime", ROOT / "deploy" / "uptime.py")
uptime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uptime)

URL = "https://joop.kg"
ENV = {"JOOP_URL": URL, "FOUNDER_BOT_TOKEN": "1:abc", "FOUNDER_CHAT_ID": "42"}


class Net:
    """Answers /health with `health` (a dict, or an exception to raise) and records Telegram messages."""

    def __init__(self, health):
        self.health, self.sent, self.calls = health, [], 0

    def __call__(self, url, data=None, timeout=None):
        if "api.telegram.org" in url:
            self.sent.append(data.decode())
            return io.BytesIO(b'{"ok": true}')
        self.calls += 1
        if isinstance(self.health, Exception):
            raise self.health
        return io.BytesIO(json.dumps(self.health).encode())


def test_up_and_nothing_to_say():
    net = Net({"ok": True})
    assert uptime.main({**ENV, "PREVIOUS": "success"}, net) == 0 and net.sent == []


def test_down_is_reported_once_per_outage():
    net = Net(urllib.error.URLError(ConnectionRefusedError()))
    assert uptime.main({**ENV, "PREVIOUS": "success"}, net) == 1
    assert net.calls == 2 and len(net.sent) == 1  # one slow answer is not an outage
    assert "joop.kg" in net.sent[0] and "%D0%BD%D0%B5%D0%B4%D0%BE%D1%81%D1%82%D1%83%D0%BF%D0%B5%D0%BD" in net.sent[0]
    again = Net(urllib.error.URLError(ConnectionRefusedError()))
    assert uptime.main({**ENV, "PREVIOUS": "failure"}, again) == 1 and again.sent == []  # already told


def test_back_up_is_reported():
    net = Net({"ok": True})
    assert uptime.main({**ENV, "PREVIOUS": "failure"}, net) == 0 and len(net.sent) == 1


def test_reasons_in_plain_words():
    assert uptime.probe(URL, Net(urllib.error.HTTPError(URL, 502, "", {}, None))) == "сервер ответил ошибкой 502"
    assert uptime.probe(URL, Net(urllib.error.URLError(ssl.SSLError()))) == "сертификат HTTPS не принят"
    assert uptime.probe(URL, Net(TimeoutError())) == "сервер не ответил за 20 секунд"
    assert uptime.probe(URL, Net({"ok": False})) == "сервер отвечает, но /health не ok"


def test_no_url_means_nothing_to_check():
    net = Net({"ok": True})
    assert uptime.main({}, net) == 0 and net.calls == 0


def test_without_secrets_it_still_fails_the_run():
    net = Net(TimeoutError())
    assert uptime.main({"JOOP_URL": URL, "PREVIOUS": ""}, net) == 1 and net.sent == []


def test_the_workflow_runs_this_script_on_a_schedule():
    text = (ROOT / ".github" / "workflows" / "uptime.yml").read_text()
    assert "python3 deploy/uptime.py" in text and 'cron: "*/10 * * * *"' in text and "vars.JOOP_URL" in text


def test_news_telegram_did_not_take_is_told_again_next_run():
    """Review of #259: an outage message Telegram refused left the run «failure», so the next run kept silent."""
    class Refusing(Net):
        def __call__(self, url, data=None, timeout=None):
            if "api.telegram.org" in url:
                raise urllib.error.URLError("telegram down")
            return super().__call__(url, data, timeout)

    assert uptime.main({**ENV, "PREVIOUS": "success"}, Refusing(urllib.error.URLError(ConnectionRefusedError()))) == 0
    assert uptime.main({**ENV, "PREVIOUS": "failure"}, Refusing({"ok": True})) == 1
