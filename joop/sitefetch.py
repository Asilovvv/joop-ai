"""The text of a business's own web page, for drafting the price list and the FAQ from a link (joop/autofill.py).

The owner pastes a link instead of the text. The server fetches that one page and keeps its visible words;
the AI then reads them exactly as if the owner had pasted them, and the owner checks the result before
anything is saved.

The link comes from a user, so it is fetched carefully: http or https on the usual ports only, every address
the host resolves to must be public (no loopback or internal network), the connection goes to the address
just checked (a DNS answer that changes in between cannot point inward), at most MAX_REDIRECTS redirects,
each checked again, and at most MAX_BYTES read.

Instagram and 2GIS show their pages only to a logged-in browser that runs their scripts, so for them the owner
is asked to copy the text instead of us fetching an empty page.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from .api import _public_ip

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 15.0  # per network step
DEADLINE = 20.0  # for the whole page, redirects included: a slow trickle cannot hold a worker
MIN_TEXT = 80  # fewer visible characters: the page is built by scripts in the browser
PORTS = {"http": 80, "https": 443}
COPY_HOSTS = {
    "instagram.com": "Instagram",
    "2gis.kg": "2ГИС",
    "2gis.ru": "2ГИС",
    "2gis.kz": "2ГИС",
    "2gis.com": "2ГИС",
}

_URL = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(:\d+)?(/\S*)?$", re.I)


def as_url(text: str) -> str:
    """The link when the pasted text is only a link (with or without https://), else ""."""
    text = (text or "").strip()
    if not text or any(c.isspace() for c in text) or not _URL.match(text):
        return ""
    return text if re.match(r"^https?://", text, re.I) else "https://" + text


def _copy_site(host: str) -> str:
    host = host.lower().rstrip(".")
    for domain, name in COPY_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return ""


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
             "header", "footer", "table", "ul", "ol", "dd", "dt", "address"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.meta: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in {"description", "og:description"} and a.get("content"):
                self.meta.append(a["content"] or "")
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def page_text(html: str) -> str:
    """The words a visitor sees, one block per line; the page description first if it adds something."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    body = "\n".join(line for line in lines if line)
    meta = [m.strip() for m in dict.fromkeys(parser.meta) if m.strip() and m.strip() not in body]
    return "\n".join(meta + [body]).strip()


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-z0-9_-]+)""", re.I)


def decode(raw: bytes, header_charset: str | None) -> str:
    """Text of the page: the header's charset, else the page's <meta charset>, else UTF-8, else windows-1251."""
    found = _META_CHARSET.search(raw[:4096])
    for name in (header_charset, found.group(1).decode("ascii") if found else None):
        if name:
            try:
                return raw.decode(name, errors="replace")
            except LookupError:
                pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")  # older Russian-language sites


def _check(url: str) -> tuple[httpx.URL | None, str, str]:
    """(url, address to connect to, error in Russian)."""
    parsed = urlparse(url)
    if parsed.scheme not in PORTS or not parsed.hostname:
        return None, "", "Ссылка должна начинаться с http:// или https://"
    if parsed.username or parsed.password or not url.isascii():
        return None, "", "Такую ссылку открыть не получилось. Скопируйте текст со страницы и вставьте его сюда."
    try:
        port = parsed.port or PORTS[parsed.scheme]
    except ValueError:
        return None, "", "Неверный порт в ссылке."
    if port != PORTS[parsed.scheme]:
        return None, "", "Откройте страницу без номера порта в ссылке."
    name = _copy_site(parsed.hostname)
    if name:
        return None, "", (f"{name} не показывает текст по ссылке без входа в аккаунт. Откройте пост или карточку, "
                          "скопируйте текст с ценами и вставьте его сюда.")
    ip = _public_ip(parsed.hostname, port)
    if not ip:
        return None, "", "Сайт по этой ссылке не открывается из интернета."
    return httpx.URL(url), ip, ""


def fetch(http: httpx.Client, url: str) -> tuple[str, str]:
    """(visible text of the page, "") or ("", why not, in Russian)."""
    started = time.monotonic()
    for _ in range(MAX_REDIRECTS + 1):
        if time.monotonic() - started > DEADLINE:
            return "", "Сайт отвечает слишком долго. Скопируйте текст со страницы и вставьте его сюда."
        target, ip, error = _check(url)
        if error or target is None:
            return "", error
        host = target.raw_host.decode("ascii")
        extensions = {"sni_hostname": host} if target.scheme == "https" else {}
        headers = {"Host": target.netloc.decode("ascii"), "Connection": "close", "User-Agent": "Mozilla/5.0 (compatible; JoopAI/1)",
                   "Accept": "text/html,text/plain"}
        try:
            with http.stream("GET", target.copy_with(host=ip), headers=headers, timeout=TIMEOUT,
                             follow_redirects=False, extensions=extensions) as r:
                if r.status_code in {301, 302, 303, 307, 308} and r.headers.get("location"):
                    url = urljoin(str(target), r.headers["location"])
                    continue
                if r.status_code >= 400:
                    return "", f"Сайт ответил ошибкой ({r.status_code}). Проверьте ссылку или вставьте текст со страницы."
                kind = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if kind not in {"text/html", "text/plain", "application/xhtml+xml", ""}:
                    return "", "По ссылке не веб-страница. Вставьте ссылку на страницу с ценами или сам текст."
                raw = bytearray()
                for chunk in r.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        break
                    if time.monotonic() - started > DEADLINE:
                        return "", "Сайт отвечает слишком долго. Скопируйте текст со страницы и вставьте его сюда."
                charset = r.charset_encoding
        except httpx.HTTPError:
            return "", "Сайт не открылся. Проверьте ссылку или вставьте текст со страницы."
        html = decode(bytes(raw[:MAX_BYTES]), charset)
        text = page_text(html) if kind != "text/plain" else html.strip()
        if len(text) < MIN_TEXT:
            return "", "На странице почти нет текста: сайт собирается в браузере. Скопируйте текст со страницы и вставьте его сюда."
        return text, ""
    return "", "Слишком много переадресаций. Вставьте ссылку на саму страницу с ценами."
