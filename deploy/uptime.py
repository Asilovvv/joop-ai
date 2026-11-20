"""Is the whole server up? Checked from outside it, by GitHub Actions (.github/workflows/uptime.yml).

The server's own alerts (joop/health.py) cannot report that the server itself is gone: a dead machine, a full disk,
an expired domain, a broken certificate. This script opens https://<domain>/health from GitHub every 10 minutes and
writes to the founder's Telegram once when it stops answering and once when it answers again.

Standard library only; run as: python deploy/uptime.py. Settings come from the environment:
JOOP_URL (the server's PUBLIC_BASE_URL), FOUNDER_BOT_TOKEN, FOUNDER_CHAT_ID, PREVIOUS (the last run's
conclusion: success, failure or empty). Exit code 1 while the server is down, so the run itself shows as failed
and the next run knows the outage is already reported."""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 20
TRIES = 2  # one slow answer is not an outage


def probe(url: str, opener=urllib.request.urlopen) -> str:
    """'' when /health answers {"ok": true}; otherwise what went wrong, in words for the founder."""
    problem = ""
    for _ in range(TRIES):
        try:
            with opener(url.rstrip("/") + "/health", timeout=TIMEOUT) as response:
                body = json.loads(response.read(4096) or b"{}")
            if body.get("ok") is True:
                return ""
            problem = "сервер отвечает, но /health не ok"
        except urllib.error.HTTPError as exc:
            problem = f"сервер ответил ошибкой {exc.code}"
        except ssl.SSLError:
            problem = "сертификат HTTPS не принят"
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError):
                problem = "сертификат HTTPS не принят"
            else:
                problem = "сервер не отвечает (нет соединения или домен не найден)"
        except (TimeoutError, OSError):
            problem = "сервер не ответил за 20 секунд"
        except ValueError:
            problem = "сервер отвечает, но /health не ok"
    return problem


def message(url: str, problem: str, previous: str) -> str:
    """What to tell the founder: only when the state changed since the last run."""
    host = urllib.parse.urlparse(url).hostname or url
    if problem and previous != "failure":
        return (f"Joop AI: сервер {host} недоступен снаружи — {problem}. Клиенты компаний сейчас не получают ответов, "
                "панель не открывается. Проверьте сервер у хостинга (включён ли, есть ли место на диске), затем "
                "docker compose ps и docker compose logs app. Когда сервер снова ответит, придёт сообщение.")
    if not problem and previous == "failure":
        return f"Joop AI: сервер {host} снова отвечает."
    return ""


def tell(token: str, chat: str, text: str, opener=urllib.request.urlopen) -> bool:
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        with opener(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=TIMEOUT) as response:
            return bool(json.loads(response.read() or b"{}").get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"Telegram message failed: {type(exc).__name__}")  # the URL holds the token
        return False


def main(env=os.environ, opener=urllib.request.urlopen) -> int:
    url = env.get("JOOP_URL", "").strip()
    if not url:
        print("JOOP_URL is not set (repository variable): nothing to check.")
        return 0
    problem = probe(url, opener)
    print(f"{url}/health: {'ok' if not problem else problem}")
    text = message(url, problem, env.get("PREVIOUS", "").strip())
    token, chat = env.get("FOUNDER_BOT_TOKEN", "").strip(), env.get("FOUNDER_CHAT_ID", "").strip()
    if text and token and chat:
        if not tell(token, chat, text, opener):
            # The run's result is the state the next run compares with. Undelivered news keeps the old state, so
            # the next run tells it again instead of staying silent about an outage nobody heard of.
            print("The message was not delivered: the next run tries again.")
            return 0 if problem else 1
    elif text:
        print("FOUNDER_BOT_TOKEN / FOUNDER_CHAT_ID secrets are not set: no Telegram message.")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main())
