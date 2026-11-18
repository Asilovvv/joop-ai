"""Labels from the product pass of 18.11: the niche picker, the site's share preview."""

import re

from fastapi.testclient import TestClient

from joop.niches import picker_packs
from joop.web.app import create_app, spheres


def test_a_lab_a_medical_centre_and_a_dental_clinic_each_see_one_niche():
    """«Стоматологии и клиники», «Медицинские центры и лаборатории» and «Медицинские лаборатории» overlapped."""
    labels = {key: pack.label.lower() for key, pack in picker_packs().items()}
    assert len(set(labels.values())) == len(labels)

    def having(stem: str) -> list[str]:
        return sorted(key for key, label in labels.items() if re.search(rf"\b{stem}", label))

    assert having("лаборатор") == ["lab"]
    assert having("клиник") == ["clinic"]  # «Ветклиники» is the vet's own word
    assert having("стоматолог") == ["dental"]


def test_spheres_agree_with_the_number():
    assert [spheres(n) for n in (1, 2, 5, 11, 21, 22, 35, 41, 112)] == [
        "1 сфера", "2 сферы", "5 сфер", "11 сфер", "21 сфера", "22 сферы", "35 сфер", "41 сфера", "112 сфер"]


def test_the_share_preview_counts_the_niches_the_site_offers(settings, rt, engine):
    """A link sent in WhatsApp or Telegram said «и ещё 15 сфер» while the home page counted 35."""
    offered = sum(1 for key in picker_packs() if key != "other")
    with TestClient(create_app(settings, rt, init=False)) as c:
        for page in ("/", "/privacy"):
            html = c.get(page).text
            preview = re.search(r'<meta property="og:description" content="([^"]*)"', html).group(1)
            assert spheres(offered) in preview and "15 сфер" not in preview, (page, preview)
        home = re.sub(r"\s+", " ", c.get("/").text)
    assert f"<b>{offered}</b><span>сфер бизнеса</span>" in home  # the home page counts the same
