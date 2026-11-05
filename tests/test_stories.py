"""Stories for Joop's own Instagram (joop/stories.py, /owner/stories)."""

from joop import stories

from .test_saas import app_client, owner_login, saas_settings  # noqa: F401  (fixtures)


def test_slides_are_well_formed_and_marks_render_as_tags():
    slides = stories.all_slides()
    assert len(slides) >= 15 and len({s["name"] for s in slides}) == len(slides)
    assert all(s["head"] and s["kind"] in ("text", "steps", "grid", "features", "table", "bullets", "cta") for s in slides)
    html = str(stories.mark("ЧТО ТАКОЕ [[ИИ]] и {{код}} <b>"))
    assert '<i class="r">ИИ</i>' in html and '<i class="w">код</i>' in html and "&lt;b&gt;" in html  # user text is escaped


def test_stories_pages_for_the_founder(app_client, business):
    assert app_client.get("/owner/stories", follow_redirects=False).headers["location"] == "/owner/login"
    owner_login(app_client)
    page = app_client.get("/owner/stories").text
    assert "/owner/stories/what-01" in page and "/owner/stories/case/" in page
    slide = app_client.get("/owner/stories/what-01").text
    assert "ИИ-АДМИНИСТРАТОР" in slide and 'class="pill"' in slide and "joop.test" in slide
    assert app_client.get("/owner/stories/nope").status_code == 404
    case = app_client.get(f"/owner/stories/case/{business.id}").text
    assert "Ак-Тиш Дент" in case and "кейса пока нет" in case  # no customers yet: says so, invents nothing
    assert app_client.get("/owner/stories/case/999").status_code == 404
