"""Subscriptions and payments: trial, paid period, access check, FreedomPay (Kyrgyzstan).

The money flow: a business signs up -> trial (TRIAL_DAYS) -> pays PRICE_SOM a month by card through
FreedomPay or by bank transfer / QR that the founder confirms in the console. When the trial or paid
period ends (plus GRACE_DAYS), the AI stops answering; messages still reach the panel and staff.
"""

from __future__ import annotations

import hashlib
import secrets
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .models import Business, Payment, Subscription

GRACE_DAYS = 3
PERIOD_DAYS = 30


def get_subscription(session: Session, business_id: int) -> Subscription | None:
    return session.exec(select(Subscription).where(Subscription.business_id == business_id)).first()


def start_trial(session: Session, business: Business, days: int, now: datetime, source: str = "signup",
                contact_name: str = "", contact_phone: str = "") -> Subscription:
    sub = get_subscription(session, business.id) or Subscription(business_id=business.id)
    sub.status = "trial"
    sub.trial_ends_at = now + timedelta(days=max(days, 0))
    sub.source = source
    sub.contact_name = contact_name.strip()
    sub.contact_phone = contact_phone.strip()
    session.add(sub)
    return sub


def access_ok(session: Session, business_id: int, now: datetime) -> bool:
    """May the AI answer this business's customers right now?"""
    sub = get_subscription(session, business_id)
    if sub is None:
        return True  # created from the command line or before billing existed
    return state(sub, now).active


@dataclass
class State:
    code: str  # trial | active | grace | expired | suspended
    active: bool
    days_left: int
    label: str


def _days(left: timedelta) -> int:
    """Whole days left, rounded up: a 14-day trial shows 14 on the day it starts, not 13."""
    return max(0, -(-int(left.total_seconds()) // 86400))


def state(sub: Subscription, now: datetime) -> State:
    if sub.status == "suspended":
        return State("suspended", False, 0, "Приостановлено")
    if sub.paid_until and now <= sub.paid_until:
        return State("active", True, _days(sub.paid_until - now), "Оплачено")
    if sub.status == "trial" and sub.trial_ends_at and now <= sub.trial_ends_at:
        return State("trial", True, _days(sub.trial_ends_at - now), "Пробный период")
    end = sub.paid_until or sub.trial_ends_at
    if end and now <= end + timedelta(days=GRACE_DAYS):
        return State("grace", True, _days(end + timedelta(days=GRACE_DAYS) - now), "Ожидает оплаты")
    return State("expired", False, 0, "Не оплачено")


def price_for(sub: Subscription | None, default_price: int) -> int:
    return (sub.price_som if sub and sub.price_som else default_price) or 0


def mark_paid(session: Session, payment: Payment, now: datetime) -> Subscription:
    """Extend the paid period by the payment's days. Paying early adds to the current period."""
    if payment.status == "paid":
        return get_subscription(session, payment.business_id)  # already applied (callbacks repeat)
    payment.status = "paid"
    payment.paid_at = now
    sub = get_subscription(session, payment.business_id) or Subscription(business_id=payment.business_id, source="owner")
    start = sub.paid_until if sub.paid_until and sub.paid_until > now else now
    sub.paid_until = start + timedelta(days=payment.period_days)
    sub.status = "active"
    session.add(payment)
    session.add(sub)
    return sub


def mrr(session: Session, now: datetime, default_price: int) -> int:
    """Monthly revenue of businesses with a paid period running now."""
    total = 0
    for sub in session.exec(select(Subscription)).all():
        if state(sub, now).code == "active":
            total += price_for(sub, default_price)
    return total


# --- FreedomPay (Paybox) merchant API ------------------------------------------------------------
# Signature: md5 of "script;value1;value2;...;secret_key", values ordered by parameter name.
# Docs: https://freedompay.kg/docs-en/merchant-api/intro and .../merchant-api/pay (checked 29 Oct 2026).


def fp_sign(script: str, params: dict, secret_key: str) -> str:
    values = [str(params[k]) for k in sorted(params) if k != "pg_sig"]
    return hashlib.md5(";".join([script, *values, secret_key]).encode("utf-8")).hexdigest()


def fp_verify(script: str, params: dict, secret_key: str) -> bool:
    sig = str(params.get("pg_sig", ""))
    return bool(sig) and secrets.compare_digest(sig, fp_sign(script, params, secret_key))


def fp_init_params(*, merchant_id: str, secret_key: str, payment: Payment, description: str, currency: str,
                   result_url: str, success_url: str, failure_url: str, testing: bool) -> dict:
    params = {
        "pg_order_id": str(payment.id),
        "pg_merchant_id": merchant_id,
        "pg_amount": str(payment.amount_som),
        "pg_currency": currency,
        "pg_description": description,
        "pg_salt": secrets.token_hex(8),
        "pg_result_url": result_url,
        "pg_success_url": success_url,
        "pg_failure_url": failure_url,
        "pg_request_method": "POST",
        "pg_testing_mode": "1" if testing else "0",
    }
    params["pg_sig"] = fp_sign("init_payment.php", params, secret_key)
    return params


def fp_parse_response(text: str) -> dict:
    """FreedomPay answers in XML; returns the child elements as a flat dict."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    return {child.tag: (child.text or "") for child in root}


def fp_reply(script: str, status: str, description: str, secret_key: str) -> str:
    params = {"pg_status": status, "pg_description": description, "pg_salt": secrets.token_hex(8)}
    params["pg_sig"] = fp_sign(script, params, secret_key)
    body = "".join(f"<{k}>{v}</{k}>" for k, v in params.items())
    return f'<?xml version="1.0" encoding="utf-8"?><response>{body}</response>'
