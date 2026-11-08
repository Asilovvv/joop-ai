"""Custom furniture and kitchens (joop/niches/furniture): «от» prices, a measurement visit, and jobs that are
made and delivered — never «можно забирать»."""

from fastapi.testclient import TestClient
from sqlmodel import select

from joop import db, jobs
from joop.agent.engine import handle_incoming
from joop.agent.llm import AgentReply
from joop.channels.base import IncomingMessage
from joop.models import Business, Job
from joop.niches import get_pack
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeLLM
from .test_web import csrf_of


def workshop(slug="mebel"):
    with db.new_session() as s:
        b = create_business(s, slug=slug, name="Мебель", password="mebel-pass-1", niche="furniture", demo=True, now_utc=NOW_UTC)
        b.example_ok = True  # its demo orders stand for real ones here
        b.telegram_bot_token = "123:TEST"
        s.commit()
        return b


def test_job_status_speaks_of_delivery_not_pickup(engine):
    assert get_pack("furniture").jobs_delivered and not get_pack("repair").jobs_delivered
    b = workshop()
    llm = FakeLLM([AgentReply("Шкаф готов."), AgentReply("Нужна квитанция.")])
    with db.new_session() as s:
        business = s.get(Business, b.id)
        handle_incoming(s, business, IncomingMessage("telegram", "f1", "text", "Шкаф готов? Квитанция 20533, телефон 0700 998 877", "", "f1"),
                        lambda: llm, NOW_UTC)
        handle_incoming(s, business, IncomingMessage("telegram", "f2", "text", "Когда будет готово?", "", "f2"), lambda: llm, NOW_UTC)
        s.commit()
    found, unknown = llm.calls[0]["system"], llm.calls[1]["system"]
    assert "- №20533: Шкаф-купе 2,4 м — готов, согласуем доставку, стоимость 60 000 сом" in found and "можно забирать" not in found
    assert "телефон, указанный при оформлении заказа" in unknown


def test_ready_notice_promises_a_delivery_day(settings, rt, engine):
    b = workshop()
    with db.new_session() as s:
        job = s.exec(select(Job).where(Job.business_id == b.id, Job.number == "20417")).one()
        business = s.get(Business, b.id)
        assert jobs.ready_text(business, job, False) == ("Ваш заказ №20417 готов: Кухня 3,2 м, фасады МДФ белые. Менеджер свяжется "
                                                        "с вами, чтобы согласовать день доставки и сборки. К оплате: 176 000 сом.")
    with TestClient(create_app(settings, rt, init=False)) as c:
        token = csrf_of(c.get("/login").text)
        c.post("/login", data={"slug": "mebel", "password": "mebel-pass-1", "csrf": token})
        page = c.get("/panel/jobs").text
        assert "Изготавливаете на заказ" in page and "Что изготавливаем" in page and "готов, согласуем доставку" in page
        assert "Принимаете вещь, телефон или машину" not in page and "можно забирать" not in page
