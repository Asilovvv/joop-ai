"""The panel as an installable app: manifest, service worker at the root, offline page, install hint."""

import json

from fastapi.testclient import TestClient

from joop.web.app import create_app

from .test_web import login


def test_manifest_worker_offline_and_install_hint(business, rt, settings):
    with TestClient(create_app(settings, rt, init=False)) as c:
        m = c.get("/static/pwa/manifest.webmanifest")
        assert m.status_code == 200
        data = json.loads(m.text)
        assert data["start_url"].startswith("/panel") and data["display"] == "standalone" and len(data["icons"]) == 4
        for icon in data["icons"]:
            assert c.get(icon["src"]).status_code == 200
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and sw.headers["content-type"].startswith("application/javascript") and "navigate" in sw.text
        assert "ИИ" not in sw.text or "каждую" not in sw.text  # pages with customers' data are never cached
        assert "caches.match(\"/offline\")" in sw.text and "/panel" not in sw.text.split("ASSETS")[1].split("]")[0]
        off = c.get("/offline")
        assert off.status_code == 200 and "Нет сети" in off.text
        login(c)
        page = c.get("/panel").text
        assert 'rel="manifest"' in page and 'serviceWorker.register("/sw.js")' in page and 'id="install"' in page
        assert "На экран Домой" in page
