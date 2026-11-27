"""Record the demo walk-through as one video, on a server of its own and with the real model.

    python scripts/record_demo.py out/demo --captions en

It starts a server on this machine with an empty database and walks the demo in a browser as a person would: a clinic
signs up; the owner asks the AI in Kyrgyz and in Russian in the test chat and books a visit; the owner confirms the
example data and opens the booking page; a customer books from a phone; the owner sees both bookings. The browser's
screen is recorded, ffmpeg joins the clips under a caption strip with a title and an end card, and one MP4 comes out
with the dialogue beside it as text.

Every answer of the AI in the video is the model's own. The run fails, and no video is kept, when the model does not
answer (the fallback reply), names another price, answers a Kyrgyz question in Russian or does not make the booking:
a recording must not show a broken flow, and nobody types answers for the AI. A run against anything but the real
model (LLM_PROVIDER=openai with an address that is not https: the test of the recorder itself) says «TEST RUN» on
the title card, on every caption and in the file's name.

The server gets nothing from this machine's environment but the model's settings (ANTHROPIC_API_KEY, JOOP_MODEL,
LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY) and reads no .env: a founder's bot or a real database cannot leak into it.

Needs Playwright with Chromium (pip install playwright && playwright install chromium) and ffmpeg.
.github/workflows/demo-video.yml runs it by hand and keeps the MP4 as an artifact of the run.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from joop.agent.engine import ERROR_REPLY  # noqa: E402
from joop.lang import RU_MESSAGE_MARKERS, looks_kyrgyz  # noqa: E402

FPS = 25
FRAME = (1920, 1080)
BAND = 90  # the caption strip under the picture
PICTURE = (FRAME[0], FRAME[1] - BAND)  # the owner's window: recorded pixel for pixel
ZOOM = 1.5  # …and drawn one and a half times larger, as on a 1280 × 660 screen: text a hall can read
PHONE = (400, 660)  # the customer's phone, in CSS pixels
PHONE_SHOWN = (600, 990)  # …enlarged by ffmpeg and centred in the frame
# The recorder films CSS pixels, so a larger device scale would not make the picture sharper; CSS zoom does. It is
# used for the panel and the site only: their layout does not depend on a width between 1280 and 1920 pixels. The
# booking page sizes its heading by the window's width, so the phone is filmed as it is.
ZOOM_SCRIPT = ("const s = new CSSStyleSheet(); s.replaceSync('html{zoom:%s}'); "
               "document.adoptedStyleSheets = [...document.adoptedStyleSheets, s];" % ZOOM)
NIGHT, INK, DIM, MINT, AMBER = "#0b1719", "#e4eeeb", "#8aa3a0", "#3fc2a5", "#f0a453"  # the site's colours
CARD_SECONDS = 4.0
MODEL_ENV = ("ANTHROPIC_API_KEY", "JOOP_MODEL", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY")
SYSTEM_ENV = ("PATH", "HOME", "LANG", "SYSTEMROOT", "TMPDIR", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
              "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")

CLINIC = "Демо Стоматология"
ASK_PRICE = "Консультация канча турат?"
PRICE = "500"  # «Консультация и осмотр» in joop/niches/dental/demo.yaml
ASK_TIME = "Когда ближайшее свободное время на консультацию?"
ASK_BOOK = "Запишите на самое раннее время. Меня зовут Айбек, телефон 0555 123 456"
SAY_YES = "Да, запишите"
CHAT_CUSTOMER, PAGE_CUSTOMER = "Айбек", "Айгуль"

# key -> (step, caption). One line of the strip each: 80 characters at most (tests/test_record_demo.py).
CAPTIONS = {
    "en": {
        "site": ("Step 1", "A clinic owner opens the site and signs up"),
        "form": ("Step 1", "Name, type of business, phone: that is the whole form"),
        "launch": ("Step 1", "At once: a working AI with an example price list, and a checklist to launch"),
        "chat": ("Step 2", "The owner tries the AI in the test chat, writing as a customer would"),
        "ask_price": ("Step 2", "A question in Kyrgyz: how much is a consultation?"),
        "price": ("Step 2", "The answer is in Kyrgyz, with the price from the price list"),
        "price_plain": ("Step 2", "The answer names the price from the price list"),
        "ask_time": ("Step 2", "A question in Russian: when is the nearest free time?"),
        "time": ("Step 2", "Only real free times are offered"),
        "ask_book": ("Step 2", "The customer asks for the earliest time and gives a name and a phone"),
        "booked": ("Step 2", "The code checks the time and saves the booking; the AI confirms it"),
        "own": ("Step 3", "The owner confirms the price list and the staff as the clinic’s own"),
        "page_on": ("Step 3", "…and opens the booking page for customers"),
        "phone": ("Step 3", "A customer opens the booking page on a phone, from the QR sign"),
        "pick": ("Step 3", "Picks a free time"),
        "contacts": ("Step 3", "Leaves a name and a phone"),
        "done": ("Step 3", "Booked, without a chat or a call"),
        "bookings": ("Step 4", "The owner sees both bookings: from the test chat and from the booking page"),
    },
    "ru": {
        "site": ("Шаг 1", "Владелец клиники открывает сайт и регистрируется"),
        "form": ("Шаг 1", "Название, сфера, телефон — это вся форма"),
        "launch": ("Шаг 1", "Сразу: рабочий ИИ с примером прайса и список шагов до запуска"),
        "chat": ("Шаг 2", "Владелец проверяет ИИ в тестовом чате: пишет как клиент"),
        "ask_price": ("Шаг 2", "Вопрос по-кыргызски: сколько стоит консультация?"),
        "price": ("Шаг 2", "Ответ по-кыргызски, цена — из прайса"),
        "price_plain": ("Шаг 2", "В ответе — цена из прайса"),
        "ask_time": ("Шаг 2", "Вопрос по-русски: когда ближайшее свободное время?"),
        "time": ("Шаг 2", "ИИ предлагает только настоящее свободное время"),
        "ask_book": ("Шаг 2", "Клиент просит самое раннее время и называет имя и телефон"),
        "booked": ("Шаг 2", "Код проверяет время и сохраняет запись, ИИ подтверждает её"),
        "own": ("Шаг 3", "Владелец подтверждает, что прайс и врачи — его собственные"),
        "page_on": ("Шаг 3", "…и открывает страницу записи для клиентов"),
        "phone": ("Шаг 3", "Клиент открывает страницу записи с телефона, по QR на стойке"),
        "pick": ("Шаг 3", "Выбирает свободное время"),
        "contacts": ("Шаг 3", "Оставляет имя и телефон"),
        "done": ("Шаг 3", "Записан — без переписки и звонка"),
        "bookings": ("Шаг 4", "Владелец видит обе записи: из тестового чата и со страницы записи"),
    },
}

CARDS = {
    "en": {
        "eyebrow": "Demo recording",
        "lead": "An AI administrator for small businesses: from sign-up to a booking in four steps",
        "facts": "Recorded automatically on {day} · model: {model} · an example clinic with fictional data",
        "end": "Every answer of the AI in this video was written by the model while it was recorded.",
        "test": "TEST RUN · not the real model",
        "test_short": "TEST RUN",
        "end_test": "A test of the recorder: the answers came from a stand-in, not from the model.",
    },
    "ru": {
        "eyebrow": "Запись демо",
        "lead": "ИИ-администратор для малого бизнеса: от регистрации до записи за четыре шага",
        "facts": "Записано автоматически {day} · модель: {model} · клиника-пример, данные вымышлены",
        "end": "Каждый ответ ИИ в этом видео написан моделью во время записи.",
        "test": "ТЕСТОВЫЙ ПРОГОН · не настоящая модель",
        "test_short": "ТЕСТОВЫЙ ПРОГОН",
        "end_test": "Проверка самой записи: ответы давала заглушка, а не модель.",
    },
}


class Broken(Exception):
    """The walk did not go as the video says it does: no video is kept."""


@dataclass
class Clip:
    video: Path
    size: tuple[int, int]  # the picture inside the frame, in video pixels
    cut: float  # seconds dropped from the start: the blank page before the first one loaded
    length: float  # seconds kept
    captions: list[tuple[float, float, str]] = field(default_factory=list)  # from, to (seconds of the kept part), key


def model_of(env: dict) -> tuple[str, bool]:
    """(the model's name for the title card, is this the real model?). Real: Anthropic, or another provider reached
    over https. A local address or plain http is the recorder's own test with a stand-in."""
    name = (env.get("JOOP_MODEL") or "").strip() or "claude-haiku-5-5"
    if (env.get("LLM_PROVIDER") or "").strip().lower() != "openai":
        return name, True
    url = urlparse((env.get("LLM_BASE_URL") or "").strip())
    local = (url.hostname or "") in ("", "localhost", "127.0.0.1", "::1")
    return name, url.scheme == "https" and not local


def is_fallback(reply: str) -> bool:
    """The reply customers get when the model cannot be called (no key, no balance, an outage)."""
    return any(line.strip() and line.strip() in reply for line in ERROR_REPLY.splitlines())


def in_russian(reply: str) -> bool:
    """A Russian sentence, by the evaluation's rule (eval/run_eval.py): a short neutral reply («Консультация — 500
    сом») is fine after a Kyrgyz question, a Russian sentence is not."""
    words = re.findall(r"[а-яё]+", reply.lower())
    return not looks_kyrgyz(reply) and sum(1 for w in words if w in RU_MESSAGE_MARKERS) >= 2


def named_times(reply: str) -> set[str]:
    """The times of day a reply names, as 09:00."""
    return {f"{int(hour):02d}:{minute}" for hour, minute in re.findall(r"\b(\d{1,2}):(\d{2})\b", reply)}


def errors_in(log: str, last: int = 3) -> str:
    """The server's own words about what went wrong: the last lines of its log that name an error (the model
    provider's answer among them: «Your credit balance is too low», an invalid key), each cut to 300 characters."""
    lines = [line.strip()[:300] for line in log.splitlines() if re.search(r"Error|error code|credit balance", line)]
    return "\n".join(dict.fromkeys(lines[-last:]))  # a retry repeats the same line


def windows(marks: list[tuple[float, str]], start: float, end: float) -> list[tuple[float, float, str]]:
    """Captions said at these moments, as (from, to, key) in seconds of a clip that runs from `start` to `end`:
    each one stays until the next is said."""
    out = []
    for i, (at, key) in enumerate(marks):
        until = marks[i + 1][0] if i + 1 < len(marks) else end
        a, b = max(at, start) - start, min(until, end) - start
        if b - a > 0.05:
            out.append((round(a, 2), round(b, 2), key))
    return out


def graph(clip: Clip) -> tuple[str, str]:
    """(ffmpeg's filter graph for one clip, the label of its result): the picture on the dark frame, each caption's
    strip (inputs 1, 2, … in the order of clip.captions) laid under it while that caption is said."""
    w, h = clip.size
    parts = [f"[0:v]fps={FPS},scale={w}:{h}:flags=lanczos,pad={FRAME[0]}:{FRAME[1]}:{(FRAME[0] - w) // 2}:0:color=0x{NIGHT[1:]}[s0]"]
    for i, (a, b, _key) in enumerate(clip.captions, 1):
        parts.append(f"[s{i - 1}][{i}:v]overlay=0:{FRAME[1] - BAND}:enable='between(t,{a:.2f},{b:.2f})'[s{i}]")
    return ";".join(parts), f"[s{len(clip.captions)}]"


def strip_html(step: str, text: str, mark: str = "") -> str:
    warn = f'<span class="w">{html.escape(mark)}</span>' if mark else ""
    return f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/fonts/fonts.css">
<style>html,body{{margin:0;background:{NIGHT}}}
.s{{width:{FRAME[0]}px;height:{BAND}px;box-sizing:border-box;padding:0 48px;display:flex;align-items:center;gap:28px;
font-family:'Golos Text',Arial,sans-serif;white-space:nowrap;border-top:2px solid #12262a}}
.k{{color:{MINT};font-weight:600;font-size:26px;letter-spacing:3px;text-transform:uppercase}}
.t{{color:{INK};font-weight:500;font-size:34px}}
.w{{margin-left:auto;color:{AMBER};font-weight:700;font-size:24px;letter-spacing:2px}}</style>
<div class="s"><span class="k">{html.escape(step)}</span><span class="t">{html.escape(text)}</span>{warn}</div>"""


def card_html(eyebrow: str, lead: str, facts: str, mark: str = "") -> str:
    warn = f'<p class="w">{html.escape(mark)}</p>' if mark else ""
    return f"""<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/fonts/fonts.css">
<style>html,body{{margin:0;background:{NIGHT}}}
.c{{width:{FRAME[0]}px;height:{FRAME[1]}px;box-sizing:border-box;padding:128px;display:flex;flex-direction:column;
justify-content:space-between;font-family:'Golos Text',Arial,sans-serif;color:{INK}}}
p{{margin:0}} .e{{color:{MINT};font-weight:600;font-size:28px;letter-spacing:4px;text-transform:uppercase}}
h1{{margin:0 0 40px;font-family:'Unbounded','Arial Black',sans-serif;font-weight:700;font-size:168px;letter-spacing:-4px;line-height:1}}
.l{{font-size:48px;line-height:1.3;max-width:1400px}} .f{{color:{DIM};font-size:30px;line-height:1.4}}
.w{{color:{AMBER};font-weight:700;font-size:44px;letter-spacing:2px;margin-top:32px}}</style>
<div class="c"><p class="e">{html.escape(eyebrow)}</p><div><h1>Joop AI</h1><p class="l">{html.escape(lead)}</p>{warn}</div>
<p class="f">{html.escape(facts)}</p></div>"""


# --- the server -----------------------------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def server_env(folder: Path, port: int, machine: dict) -> dict:
    """The environment of the recorder's server: of the machine's own, what a program needs to run and reach the
    network, and the model's settings. Nothing else gets in: no founder's bot, no channel tokens, no real database;
    JOOP_ENV_FILE names a file that does not exist, so no .env is read either."""
    env = {k: machine[k] for k in SYSTEM_ENV if k in machine}
    env.update({k: machine[k] for k in MODEL_ENV if machine.get(k)})
    env.update(PYTHONPATH=str(ROOT), JOOP_ENV_FILE=str(folder / "no.env"), DATABASE_URL=f"sqlite:///{folder / 'demo.db'}",
               SESSION_SECRET=secrets.token_hex(32), SECURE_COOKIES="0", PUBLIC_BASE_URL=f"http://127.0.0.1:{port}",
               OWNER_PASSWORD=secrets.token_urlsafe(18))
    return env


def start_server(folder: Path, port: int) -> subprocess.Popen:
    """A server of its own, with an empty database in `folder`."""
    env = server_env(folder, port, dict(os.environ))
    log = open(folder / "server.log", "w")
    subprocess.run([sys.executable, "-m", "joop", "migrate"], env=env, cwd=folder, check=True, stdout=log, stderr=subprocess.STDOUT)
    server = subprocess.Popen([sys.executable, "-m", "joop", "serve", "--host", "127.0.0.1", "--port", str(port)],
                              env=env, cwd=folder, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        if server.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as answer:
                if answer.status == 200:
                    return server
        except OSError:
            time.sleep(0.5)
    server.kill()
    raise Broken("The server did not start: " + (folder / "server.log").read_text()[-800:])


# --- the browser ----------------------------------------------------------------------------------------------------


class Shot:
    """One recorded browser window: its page, its video and the captions said while it ran."""

    def __init__(self, browser, folder: Path, mobile: bool = False, storage=None) -> None:
        window = PHONE if mobile else PICTURE
        self.size = PHONE_SHOWN if mobile else PICTURE  # in the film
        self.context = browser.new_context(
            viewport={"width": window[0], "height": window[1]}, device_scale_factor=1, locale="ru-RU", color_scheme="light",
            is_mobile=mobile, has_touch=mobile, storage_state=storage, record_video_dir=str(folder),
            record_video_size={"width": window[0], "height": window[1]})
        if not mobile:
            self.context.add_init_script(ZOOM_SCRIPT)
        self.page = self.context.new_page()
        self.created = time.monotonic()
        self.loaded: float | None = None
        self.marks: list[tuple[float, str]] = []

    def settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # a page that keeps a connection open: it is loaded enough
            pass
        self.page.wait_for_timeout(400)

    def open(self, url: str) -> None:
        self.page.goto(url)
        self.settle()
        if self.loaded is None:
            self.loaded = time.monotonic()

    def say(self, key: str) -> None:
        self.marks.append((time.monotonic(), key))

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def point(self, target) -> None:
        """The video has no mouse pointer: an amber outline shows what is pressed next."""
        target.scroll_into_view_if_needed()
        target.evaluate("el => { el.style.outline = '4px solid #f0a453'; el.style.outlineOffset = '3px'; }")
        self.hold(0.7)

    def press(self, target, leaves: bool = True) -> None:
        """Press a link or a button; `leaves`: another page opens."""
        self.point(target)
        if leaves:
            with self.page.expect_navigation(timeout=120000):
                target.click()
            self.settle()
        else:
            target.click()
            target.evaluate("el => { el.style.outline = ''; }")
            self.hold(0.3)

    def write(self, selector: str, text: str) -> None:
        field_ = self.page.locator(selector).first
        field_.scroll_into_view_if_needed()
        field_.click()
        self.page.keyboard.type(text, delay=45)
        self.hold(0.3)

    def close(self) -> Clip:
        end = time.monotonic()
        video = self.page.video
        self.context.close()  # the video file is complete only now
        start = self.loaded or self.created
        return Clip(Path(video.path()), self.size, round(start - self.created, 2), round(end - start, 2),
                    windows(self.marks, start, end))


def last_reply(page) -> str:
    replies = page.locator(".msgs .msg.ai")
    if not replies.count():
        return ""
    return replies.last.evaluate("el => { const copy = el.cloneNode(true); copy.querySelectorAll('.meta').forEach(m => m.remove()); "
                                 "return copy.textContent.trim(); }")


def ask(shot: Shot, text: str, key: str, talk: list[tuple[str, str]]) -> str:
    """Type a customer's message into the test chat, send it and return the AI's reply. The model answers while the
    page loads: the wait in the video is the model's own."""
    before = shot.page.locator(".msgs .msg.ai").count()
    shot.say(key)
    shot.write("#text", text)
    shot.hold(0.8)
    shot.press(shot.page.locator("form#end button[type=submit]"))
    reply = last_reply(shot.page) if shot.page.locator(".msgs .msg.ai").count() > before else ""
    talk += [("customer", text), ("ai", reply)]
    if not reply or is_fallback(reply):
        raise Broken("The model did not answer (the fallback reply or nothing): check the key and the balance. "
                     f"After «{text}» the chat shows: {reply[:200]!r}")
    return reply


def has_booking(shot: Shot, base: str, name: str) -> bool:
    return name in shot.context.request.get(f"{base}/panel/bookings").text()


def walk(browser, base: str, folder: Path) -> tuple[list[Clip], list[tuple[str, str]]]:
    """The demo, recorded: three clips (the owner, the customer's phone, the owner again) and the dialogue."""
    talk: list[tuple[str, str]] = []

    # 1. sign-up
    owner = Shot(browser, folder)
    owner.open(base + "/")
    owner.say("site")
    owner.hold(3.5)
    owner.press(owner.page.locator('a[href="/signup"]').first)
    owner.say("form")
    owner.write("input[name=name]", CLINIC)
    owner.page.select_option("select[name=niche]", "dental")
    owner.hold(0.5)
    owner.write("input[name=contact_name]", "Бектур")
    owner.write("input[name=phone]", "0555 010 203")
    owner.write("input[name=password]", secrets.token_urlsafe(12))
    owner.press(owner.page.locator('form[action="/signup"] button[type=submit]'))
    if "/panel" not in owner.page.url:
        raise Broken(f"Sign-up did not open the panel: {owner.page.url}")
    owner.say("launch")
    owner.hold(5)

    # 2. the test chat, on the real model
    owner.open(base + "/panel/try")
    owner.say("chat")
    owner.hold(3)
    reply = ask(owner, ASK_PRICE, "ask_price", talk)
    if PRICE not in reply or in_russian(reply):
        raise Broken(f"To «{ASK_PRICE}» the AI must name {PRICE} som, and not in Russian; it said: {reply[:300]!r}")
    owner.say("price" if looks_kyrgyz(reply) else "price_plain")  # the caption says only what the reply shows
    owner.hold(6)
    reply = ask(owner, ASK_TIME, "ask_time", talk)
    schedule = re.sub(r"<[^>]+>", " ", owner.context.request.get(f"{base}/panel/slots").text())
    named = named_times(reply)
    if not named or any(t not in schedule for t in named):  # «Окна» lists every time of the clinic's schedule
        raise Broken(f"To «{ASK_TIME}» the AI must name times from the schedule; it said: {reply[:300]!r}")
    owner.say("time")
    owner.hold(6)
    ask(owner, ASK_BOOK, "ask_book", talk)
    if not has_booking(owner, base, CHAT_CUSTOMER):
        owner.hold(4)
        ask(owner, SAY_YES, "ask_book", talk)  # the AI asked to confirm: the customer does, once
    if not has_booking(owner, base, CHAT_CUSTOMER):
        raise Broken(f"The AI did not book {CHAT_CUSTOMER}. Its last reply: {last_reply(owner.page)[:300]!r}")
    owner.say("booked")
    owner.hold(7)

    # 3. the example becomes the clinic's own data, the booking page opens
    owner.open(base + "/panel")
    owner.say("own")
    own = owner.page.locator('form[action="/panel/example/ok"] button')
    if not own.count():
        raise Broken("The dashboard has no «Это наши настоящие данные» button")
    owner.hold(1.5)
    owner.press(own.first)
    owner.hold(2.5)
    owner.open(base + "/panel/menu")
    owner.say("page_on")
    for name in ("enabled", "self_booking"):
        box = owner.page.locator(f"input[name={name}]").first
        if not box.is_checked():
            owner.press(box, leaves=False)
    owner.press(owner.page.locator("form:has(input[name=self_booking]) button[type=submit]").first)
    found = re.search(r"/m/([a-z0-9-]+)/book", owner.page.content())
    if not found:
        raise Broken("The booking page's address is not on «Прайс онлайн» after saving")
    owner.hold(3)
    signed_in = owner.context.storage_state()
    clips = [owner.close()]

    # the customer, on a phone
    phone = Shot(browser, folder, mobile=True)
    phone.open(f"{base}/m/{found.group(1)}/book")
    phone.say("phone")
    phone.hold(3.5)
    times = phone.page.locator('a[href*="slot="]')
    if times.count() < 3:
        raise Broken(f"The booking page offers {times.count()} free times; the example opens dozens")
    phone.say("pick")
    phone.press(times.nth(2))
    phone.say("contacts")
    phone.write("input[name=name]", PAGE_CUSTOMER)
    phone.write("input[name=phone]", "0555 777 888")
    phone.hold(1.5)  # with the typing above: longer than the form's shortest time for a person
    phone.press(phone.page.locator("form.book button[type=submit]").first)
    if "slot=" in phone.page.url:
        raise Broken("The booking page did not take the booking: " + phone.page.locator("body").inner_text()[:300])
    phone.say("done")
    phone.hold(5)
    clips.append(phone.close())

    # 4. the owner again
    owner = Shot(browser, folder, storage=signed_in)
    owner.open(base + "/panel/bookings")
    listed = owner.page.locator("body").inner_text()
    if CHAT_CUSTOMER not in listed or PAGE_CUSTOMER not in listed:
        raise Broken("«Записи» does not show both bookings")
    owner.say("bookings")
    owner.hold(7)
    clips.append(owner.close())
    return clips, talk


# --- the film -------------------------------------------------------------------------------------------------------


def render(browser, base: str, pages: dict[str, tuple[str, int]], folder: Path) -> dict[str, Path]:
    """Captions and cards as pictures, in the site's own fonts: name -> (html, height) becomes name -> PNG. The html is
    served under the server's address, so /static/fonts loads as on the site."""
    def serve(body: str):
        def answer(route) -> None:  # one parameter: with two, Playwright passes the request as the second
            route.fulfill(content_type="text/html; charset=utf-8", body=body)
        return answer

    out: dict[str, Path] = {}
    context = browser.new_context(viewport={"width": FRAME[0], "height": FRAME[1]}, device_scale_factor=1)
    page = context.new_page()
    for name, (body, height) in pages.items():
        address = f"{base}/__film/{name}"
        page.route(address, serve(body))
        page.set_viewport_size({"width": FRAME[0], "height": height})
        page.goto(address)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(150)
        out[name] = folder / f"{name}.png"
        page.screenshot(path=str(out[name]))
    context.close()
    return out


ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
          "-video_track_timescale", "12800", "-an"]


def run_ffmpeg(args: list[str]) -> None:
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if done.returncode:
        raise Broken("ffmpeg: " + done.stderr[-1500:])


def film(clips: list[Clip], pictures: dict[str, Path], folder: Path, out: Path) -> float:
    """Title card, the clips under their captions, end card: one MP4. Returns its length in seconds."""
    parts = []

    def still(name: str) -> None:
        parts.append(folder / f"part{len(parts)}.mp4")
        run_ffmpeg(["-loop", "1", "-framerate", str(FPS), "-t", str(CARD_SECONDS), "-i", str(pictures[name]), *ENCODE, str(parts[-1])])

    still("title")
    for clip in clips:
        parts.append(folder / f"part{len(parts)}.mp4")
        strips = [arg for _a, _b, key in clip.captions for arg in ("-i", str(pictures[key]))]
        graph_, result = graph(clip)
        run_ffmpeg(["-ss", str(clip.cut), "-t", str(clip.length), "-i", str(clip.video), *strips,
                    "-filter_complex", graph_, "-map", result, *ENCODE, str(parts[-1])])
    still("end")
    (folder / "parts.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(folder / "parts.txt"), "-c", "copy", "-movflags", "+faststart", str(out)])
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.split()
    width, height = (int(x) for x in probe[0].split(",")[:2])
    length = float(probe[1])
    expected = 2 * CARD_SECONDS + sum(c.length for c in clips)
    if (width, height) != FRAME or abs(length - expected) > 3:
        raise Broken(f"The film came out {width}×{height}, {length:.1f} s; expected {FRAME[0]}×{FRAME[1]}, about {expected:.1f} s")
    return length


def record(out: Path, lang: str) -> Path:
    from playwright.sync_api import sync_playwright

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise Broken(f"{tool} is not installed")
    model, real = model_of(dict(os.environ))
    words, cards = CAPTIONS[lang], CARDS[lang]
    mark = "" if real else cards["test"]
    day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Bishkek")).strftime("%d.%m.%Y")
    target = out / f"joop-demo-{'' if real else 'TEST-'}{lang}.mp4"
    with tempfile.TemporaryDirectory(prefix="joop-demo-") as tmp:
        folder = Path(tmp)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = start_server(folder, port)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    clips, talk = walk(browser, base, folder)
                except Broken as problem:  # the server knows why the model did not answer
                    said = errors_in((folder / "server.log").read_text(errors="replace"))
                    raise Broken(f"{problem}\nThe server's log says:\n{said}" if said else str(problem)) from None
                pages = {key: (strip_html(step, text, "" if real else cards["test_short"]), BAND) for key, (step, text) in words.items()}
                facts = cards["facts"].format(day=day, model=model)
                pages["title"] = (card_html(cards["eyebrow"], cards["lead"], facts, mark), FRAME[1])
                pages["end"] = (card_html(cards["eyebrow"], cards["end"] if real else cards["end_test"], facts, mark), FRAME[1])
                pictures = render(browser, base, pages, folder)
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        length = film(clips, pictures, folder, target)
    lines = [f"Joop AI, demo recording of {day}. Model: {model}{'' if real else ' — ' + cards['test']}.", ""]
    lines += [f"{'Customer' if who == 'customer' else 'AI'}: {text}" for who, text in talk]
    target.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{target}: {length:.0f} s, {target.stat().st_size / 1e6:.1f} MB; the dialogue is in {target.with_suffix('.txt').name}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the demo walk-through as one MP4, on the real model.")
    parser.add_argument("out", help="folder for joop-demo-<captions>.mp4 and the dialogue as text")
    parser.add_argument("--captions", choices=sorted(CAPTIONS), default="en", help="language of the captions and cards")
    args = parser.parse_args()
    try:
        record(Path(args.out), args.captions)
    except Broken as problem:
        print(f"No video: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
