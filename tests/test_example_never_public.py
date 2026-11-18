"""The sign-up example is fictional in every niche: none of it reaches a page a customer can open.

The same leak was fixed three times, page by page (#238, #241, #242); this walks every niche and every public page."""

import os
import re

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db
from joop.models import Faq, Service, Staff
from joop.niches import get_pack
from joop.presets import create_business
from joop.profile import load_profile
from joop.web.app import create_app

from .conftest import NOW_UTC

NICHES = sorted(d for d in os.listdir("joop/niches") if os.path.isfile(f"joop/niches/{d}/demo.yaml"))
PAGES = ("/m/{slug}", "/c/{slug}", "/c/{slug}/widget.js", "/api/mobile/places/{slug}")


def test_there_are_niches_to_walk():
    assert len(NICHES) >= 30 and "dental" in NICHES


def test_no_public_page_of_a_new_business_shows_the_example(settings, rt, engine):
    leaks = []
    with TestClient(create_app(settings, rt, init=False)) as c:
        for niche in NICHES:
            slug = f"new-{niche}"
            with db.new_session() as s:
                b = create_business(s, slug=slug, name=f"Фирма {niche}", password="fresh-pass", niche=niche, demo=True,
                                    now_utc=NOW_UTC)
                b.menu_enabled = b.bot_enabled = True  # the owner turned everything on before filling anything in
                s.add(b)
                s.commit()
                demo = load_profile(get_pack(niche).demo_file)
                marks = {str(demo.get(f) or "").strip() for f in ("address", "phone", "description", "hours")}
                for model in (Service, Staff):
                    marks |= {row.name for row in s.exec(select(model).where(model.business_id == b.id)).all()}
                marks |= {row.answer for row in s.exec(select(Faq).where(Faq.business_id == b.id)).all()}
            marks.discard("")
            for page in PAGES:
                r = c.get(page.format(slug=slug))
                assert r.status_code == 200, (niche, page, r.status_code)
                found = sorted(m for m in marks if m in r.text)
                if "демо" in r.text.lower() or re.search(r"555[\s -]?000", r.text):
                    found.append("демо / 555 000")
                if found:
                    leaks.append((niche, page, found[:3]))
    assert not leaks, leaks
