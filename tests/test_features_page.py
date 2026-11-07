"""Public «Возможности» page."""

from fastapi.testclient import TestClient

from joop.web.app import FEATURE_GROUPS, create_app


def test_features_page_lists_every_group_and_is_linked(settings, rt):
    with TestClient(create_app(settings, rt, init=False)) as c:
        r = c.get("/vozmozhnosti")
        assert r.status_code == 200
        for group in FEATURE_GROUPS:
            assert group["title"] in r.text
            for title, _ in group["cards"]:
                assert title in r.text
        assert "Чего Joop пока не делает" in r.text and "Не фискальная касса" in r.text
        assert 'href="/vozmozhnosti"' in c.get("/").text
