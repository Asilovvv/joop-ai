"""Joop Studio pages: public order form, the founder's studio queue, and hosted sites /site/<slug>."""

from __future__ import annotations

import json
import logging
import re
import time

from fastapi import APIRouter, Form, HTTPException, Request
from sqlmodel import select

from .. import studio
from ..db import new_session
from ..models import StudioRequest
from ..niches import all_packs, get_pack
from ..timeutil import utcnow
from .app import _back, _check_csrf, _flash, _rt, _settings, templates
from .saas import _owner, _owner_render, slugify

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/studio")
def studio_form(request: Request):
    from .app import _csrf

    s = _settings(request)
    ctx = {"request": request, "csrf": _csrf(request), "flashes": request.session.pop("flash", []), "kinds": studio.KINDS,
           "packs": {k: p for k, p in all_packs().items()}, "legal_name": s.company_legal_name, "email": s.contact_email,
           "phone": s.contact_phone, "telegram": s.contact_telegram, "updated": "30.10.2026"}
    return templates.TemplateResponse(request, "site_studio.html", ctx)


@router.post("/studio")
def studio_order(request: Request, kind: str = Form("site"), business_name: str = Form(""), contact_name: str = Form(""),
                 phone: str = Form(""), niche: str = Form("other"), description: str = Form(""), website: str = Form(""),
                 csrf: str = Form("")):
    _check_csrf(request, csrf)
    if website:  # honeypot
        return _back("/studio")
    if time.time() - float(request.session.get("studio_at", 0) or 0) < 30:
        _flash(request, "Заявка уже отправлена. Подождите полминуты, если хотите отправить ещё одну.", "error")
        return _back("/studio#form")
    if len(business_name.strip()) < 2 or len(re.sub(r"\D", "", phone)) < 9 or len(description.strip()) < 20:
        _flash(request, "Укажите название, телефон и опишите, что нужно (хотя бы пару предложений).", "error")
        return _back("/studio#form")
    with new_session() as s:
        s.add(StudioRequest(kind=kind if kind in studio.KINDS else "other", business_name=business_name.strip()[:120],
                            contact_name=contact_name.strip()[:80], phone=phone.strip()[:40],
                            niche=niche if niche in all_packs() else "other", description=description.strip()[:4000]))
        s.commit()
    request.session["studio_at"] = time.time()
    _flash(request, "Спасибо! Заявка принята — мы свяжемся с вами по телефону или в WhatsApp.")
    return _back("/studio#form")


@router.get("/site/{slug}")
def hosted_site(request: Request, slug: str):
    with new_session() as s:
        r = s.exec(select(StudioRequest).where(StudioRequest.public_slug == slug, StudioRequest.published == True)).first()  # noqa: E712
    if r is None or not r.content_json:
        raise HTTPException(status_code=404)
    site = json.loads(r.content_json)
    return templates.TemplateResponse(request, "site_generated.html", {
        "request": request, "site": site, "name": r.business_name, "wa": studio.phone_digits(site.get("phone") or r.phone),
        "flashes": [], "business": None,
    })


@router.get("/owner/studio")
def owner_studio(request: Request, status: str = ""):
    _owner(request)
    with new_session() as s:
        q = select(StudioRequest).order_by(StudioRequest.updated_at.desc())
        if status in studio.STATUSES:
            q = q.where(StudioRequest.status == status)
        items = s.exec(q).all()
    rows = [{"r": r, "site": json.loads(r.content_json) if r.content_json else None} for r in items]
    return _owner_render(request, "owner_studio.html", active="studio", rows=rows, kinds=studio.KINDS,
                         statuses=studio.STATUSES, current=status, base=_settings(request).public_base_url)


@router.post("/owner/studio/{rid}")
async def owner_studio_action(request: Request, rid: int):
    _owner(request)
    form = await request.form()
    _check_csrf(request, str(form.get("csrf", "")))
    action = str(form.get("action", ""))
    with new_session() as s:
        r = s.get(StudioRequest, rid)
        if r is None:
            raise HTTPException(status_code=404)
        if action == "draft":
            try:
                site = studio.draft_site(_rt(request).get_llm(), r.business_name, get_pack(r.niche).label, r.description, r.phone)
            except Exception:
                log.exception("Studio draft failed")
                site = None
            if site is None:
                _flash(request, "ИИ не смог сделать черновик. Проверьте ANTHROPIC_API_KEY или дополните описание.", "error")
            else:
                r.content_json = json.dumps(site, ensure_ascii=False)
                r.status = "draft" if r.status == "new" else r.status
                if not r.public_slug:
                    base, slug, n = slugify(r.business_name), slugify(r.business_name), 2
                    while s.exec(select(StudioRequest.id).where(StudioRequest.public_slug == slug)).first():
                        slug, n = f"{base}-{n}", n + 1
                    r.public_slug = slug
                _flash(request, "Черновик сайта готов. Проверьте текст, при необходимости поправьте и опубликуйте.")
        elif action == "save" and r.content_json:
            site = json.loads(r.content_json)
            for key in ("headline", "subheadline", "about", "address", "hours", "phone", "instagram", "cta"):
                if key in form:
                    site[key] = studio._clean(form.get(key), studio.LIMITS[key])
            r.content_json = json.dumps(site, ensure_ascii=False)
            _flash(request, "Сохранено.")
        elif action in {"publish", "unpublish"} and r.content_json:
            r.published = action == "publish"
            _flash(request, f"Сайт {'опубликован' if r.published else 'снят с публикации'}: /site/{r.public_slug}")
        elif action == "status" and str(form.get("status", "")) in studio.STATUSES:
            r.status = str(form.get("status"))
            try:
                r.price_som = max(0, int(str(form.get("price_som") or 0)))
            except ValueError:
                pass
        else:
            raise HTTPException(status_code=400)
        r.updated_at = utcnow()
        s.add(r)
        s.commit()
    return _back(f"/owner/studio#r{rid}")
