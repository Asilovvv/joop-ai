"""Drafting the price list from a link: the page is fetched safely and only its visible text is used."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from joop import sitefetch
from joop.web import autofill as page
from joop.web.app import create_app

from .test_autofill import ANSWER, Writer
from .test_web import login

PAGE = """<html><head><title>Салон</title><meta name="description" content="Салон красоты в центре Бишкека">
<style>.x{color:red}</style><script>var price = 999;</script></head>
<body><nav><ul><li>Главная</li><li>Цены</li></ul></nav>
<h2>Цены</h2><table><tr><td>Маникюр с покрытием</td><td>1 200 сом</td></tr><tr><td>Педикюр</td><td>от 1 500 сом</td></tr></table>
<p>Работаем ежедневно с 9:00 до 21:00, парковка во дворе.</p></body></html>"""


class FakeWeb:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        status, headers, body = self.routes[request.headers["host"] + request.url.path]
        return httpx.Response(status, headers=headers, content=body.encode())

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def public(monkeypatch):
    """Every host resolves to a public address, except the ones named internal."""
    monkeypatch.setattr(sitefetch, "_public_ip", lambda host, port=443: "" if "internal" in host else "203.0.113.7")


def test_as_url():
    assert sitefetch.as_url("salon.kg/prices") == "https://salon.kg/prices"
    assert sitefetch.as_url(" https://salon.kg ") == "https://salon.kg"
    assert sitefetch.as_url("Маникюр 1 200, сайт salon.kg") == ""
    assert sitefetch.as_url("Стрижка 500") == "" and sitefetch.as_url("") == ""


def test_page_text_keeps_what_a_visitor_sees():
    text = sitefetch.page_text(PAGE)
    assert "Маникюр с покрытием\n1 200 сом" in text and "парковка во дворе" in text
    assert text.startswith("Салон красоты в центре Бишкека")  # the page description, first
    assert "999" not in text and "color" not in text and "Салон\n" not in text  # scripts, styles, title


def test_fetch_follows_a_checked_redirect_and_connects_to_the_checked_address(public):
    web = FakeWeb({"salon.kg/": (301, {"location": "https://www.salon.kg/prices"}, ""),
                   "www.salon.kg/prices": (200, {"content-type": "text/html; charset=utf-8"}, PAGE)})
    text, error = sitefetch.fetch(web.client(), "https://salon.kg/")
    assert error == "" and "Педикюр" in text
    assert all(r.url.host == "203.0.113.7" for r in web.seen)  # pinned: no second DNS lookup
    assert web.seen[1].extensions["sni_hostname"] == "www.salon.kg"


def test_fetch_refuses_inward_and_unsuitable_links(public):
    web = FakeWeb({"salon.kg/": (302, {"location": "http://internal.local/admin"}, ""),
                   "empty.kg/": (200, {"content-type": "text/html"}, "<div id=app></div><script>render()</script>"),
                   "files.kg/a.pdf": (200, {"content-type": "application/pdf"}, "%PDF"),
                   "gone.kg/": (404, {}, "")})
    http = web.client()
    assert "не открывается из интернета" in sitefetch.fetch(http, "https://salon.kg/")[1]
    assert len(web.seen) == 1  # the internal address was never requested
    assert "почти нет текста" in sitefetch.fetch(http, "https://empty.kg/")[1]
    assert "не веб-страница" in sitefetch.fetch(http, "https://files.kg/a.pdf")[1]
    assert "(404)" in sitefetch.fetch(http, "https://gone.kg/")[1]
    assert "без номера порта" in sitefetch.fetch(http, "https://salon.kg:8080/")[1]
    assert "Instagram не показывает" in sitefetch.fetch(http, "https://www.instagram.com/salon/")[1]
    assert "2ГИС" in sitefetch.fetch(http, "https://2gis.kg/bishkek/firm/1")[1]
    assert len(web.seen) == 4  # port, Instagram and 2GIS were refused before any request


def test_fetch_stops_after_too_many_redirects(public):
    web = FakeWeb({"loop.kg/": (302, {"location": "/"}, "")})
    assert "переадресаций" in sitefetch.fetch(web.client(), "https://loop.kg/")[1]
    assert len(web.seen) == sitefetch.MAX_REDIRECTS + 1


@pytest.fixture
def web(settings, rt, business):
    page.reset_limits()
    with TestClient(create_app(settings, rt, init=False)) as c:
        yield c
    page.reset_limits()


def test_panel_drafts_from_a_link(web, rt, public):
    site = FakeWeb({"salon.kg/prices": (200, {"content-type": "text/html"}, PAGE)})
    rt.http = site.client()
    rt._llm = writer = Writer(json.dumps(ANSWER, ensure_ascii=False))
    token = login(web)
    html = web.post("/panel/autofill", data={"csrf": token, "source": "salon.kg/prices"}).text
    assert "Проверьте, что нашёл ИИ" in html
    assert "Маникюр с покрытием" in writer.calls[0] and "<td>" not in writer.calls[0]  # the AI read the page's text
    msg = web.post("/panel/autofill", data={"csrf": token, "source": "instagram.com/salon"}).text
    assert "скопируйте текст с ценами" in msg and len(writer.calls) == 1  # no AI call for a page we could not read
