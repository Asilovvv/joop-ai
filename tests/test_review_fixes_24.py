"""Independent review of #301–#310: «Заполнить по-кыргызски» must not turn the sign-up example's prices into the
owner's own. A row is the example while every field the sign-up copied is unchanged (#303); a Kyrgyz name the
example never had, written by the bulk fill, is not the owner typing their own price."""

import json

from sqlmodel import select

from joop import db, kyrgyz, samples
from joop.models import Business, Service
from joop.presets import create_business
from joop.web.saas import checklist

from .conftest import NOW_UTC


class _Writer:
    """The model's Kyrgyz wordings: one per name sent."""

    def write(self, instruction, text, usage):
        return json.dumps([f"{name} (кырг.)" for name in json.loads(text)], ensure_ascii=False)


def test_the_kyrgyz_fill_keeps_the_example_prices_hidden_from_customers(engine):
    with db.new_session() as s:
        b = create_business(s, slug="smile", name="Смайл", password="smile-pass", niche="dental", demo=True, now_utc=NOW_UTC)
        s.commit()
        rows = s.exec(select(Service).where(Service.business_id == b.id)).all()
        assert rows and all(r.name_ky == "" for r in rows)  # the dental example has no Kyrgyz names
        before = samples.hidden_from_customers(s, b, "web").services
        assert before == {r.id for r in rows}
        result = kyrgyz.fill_missing(s, b, _Writer())
        s.commit()
        assert result.filled == len(rows)
        assert all(r.name_ky for r in s.exec(select(Service).where(Service.business_id == b.id)).all())
        assert samples.hidden_from_customers(s, s.get(Business, b.id), "web").services == before
        step = next(x for x in checklist(s, s.get(Business, b.id), NOW_UTC) if x["key"] == "prices")
        assert step["done"] is False


def test_a_changed_price_still_makes_the_row_the_owners(engine):
    with db.new_session() as s:
        b = create_business(s, slug="smile", name="Смайл", password="smile-pass", niche="dental", demo=True, now_utc=NOW_UTC)
        s.commit()
        row = s.exec(select(Service).where(Service.business_id == b.id).order_by(Service.id)).first()
        row.name_ky, row.price = "Кеңеш", "700"
        s.add(row)
        s.commit()
        assert row.id not in samples.hidden_from_customers(s, b, "web").services
