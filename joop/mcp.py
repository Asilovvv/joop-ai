"""Joop as an MCP server: another AI assistant (Claude, ChatGPT, a partner's agent) reads a business's prices and free
times and books a customer, through the same rules as POST /api/v1/bookings (joop/api.py).

Transport: MCP "Streamable HTTP" with plain JSON replies — POST /mcp with a JSON-RPC 2.0 message, the business's API
key as a Bearer token. Methods: initialize, ping, tools/list, tools/call; notifications get 202 and no body.

Tools:
- business_info — name, address, phone, hours, the price list (no sign-up example, nothing in the stop list);
- free_slots — free times, optionally for one day (only when the owner allowed booking through the API);
- book — books one of them for a named customer with a phone.

Reading needs the key; booking also needs «Разрешить запись через API» on, like the REST API. The key goes in the
Authorization header: clients that set headers can use this (Claude Desktop through mcp-remote, SDK clients, partners'
agents); hosted connectors that need OAuth discovery cannot yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from . import api
from .models import Business, Service
from .samples import hidden_from_customers

SUPPORTED = ("2025-11-25", "2025-06-18")  # without JSON-RPC batches (2025-03-26 and older required them)
SERVER = {"name": "joop", "version": "1.0"}

TOOLS = [
    {"name": "business_info",
     "description": "The business's name, address, phone, working hours and price list (prices in som).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "free_slots",
     "description": "Free times to book a customer into, in the business's local time. One day (up to 60 days ahead), "
                    "or without a date the next 14 days.",
     "inputSchema": {"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}},
                     "additionalProperties": False}},
    {"name": "book",
     "description": "Book a customer into one free time from free_slots. Ask the customer's name and phone first.",
     "inputSchema": {"type": "object", "required": ["slot_id", "name", "phone"], "additionalProperties": False,
                     "properties": {"slot_id": {"type": "integer"}, "name": {"type": "string"},
                                    "phone": {"type": "string", "description": "e.g. 0555 123 456"},
                                    "service": {"type": "string"}, "party_size": {"type": "integer", "minimum": 1}}}},
]


def _rpc(id_: Any, result: Any = None, error: tuple[int, str] | None = None) -> dict:
    out: dict[str, Any] = {"jsonrpc": "2.0", "id": id_}
    if error:
        out["error"] = {"code": error[0], "message": error[1]}
    else:
        out["result"] = result
    return out


def _text(data: Any, is_error: bool = False) -> dict:
    import json

    body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return {"content": [{"type": "text", "text": body}], "isError": is_error}


def business_info(session: Session, business: Business) -> dict:
    hidden = hidden_from_customers(session, business, "mcp")
    services = session.exec(select(Service).where(Service.business_id == business.id, Service.available == True)  # noqa: E712
                            .order_by(Service.sort, Service.id)).all()
    shown = {f: "" if f in hidden.contacts else getattr(business, f) for f in ("address", "phone")}
    return {"name": business.name, "address": shown["address"], "phone": shown["phone"],
            "hours": "" if hidden.hours else (business.hours_text or f"{business.work_start}–{business.work_end}"),
            "timezone": business.timezone,
            "services": [{"name": s.name, "price": s.price, "note": s.note} for s in services if s.id not in hidden.services]}


Notes = list[str]


def call(session: Session, business: Business, name: str, args: dict, now_local: datetime, now_utc: datetime,
         notes: Notes) -> dict:
    """One tool call. Booking notes for staff go to `notes` (sent by the caller after commit)."""
    if name == "business_info":
        return _text(business_info(session, business))
    if name in ("free_slots", "book") and not business.api_booking:
        return _text("Booking through Joop is turned off by this business.", True)
    if name == "free_slots":
        raw = str(args.get("date") or "")
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
        except ValueError:
            return _text("date must be YYYY-MM-DD", True)
        if day and not now_local.date() <= day <= now_local.date() + timedelta(days=api.DAY_AHEAD):
            return _text(f"date must be from today to {api.DAY_AHEAD} days ahead", True)
        return _text({"slots": api.free_slots(session, business, day, now_local), "timezone": business.timezone})
    if name == "book":
        done = api.book(session, business, args, now_local, now_utc)
        if done.booking is None:
            return _text(done.error, True)
        notes.append(api.booking_note(done.booking))
        return _text({"booked": api.booking_json(done.booking), "timezone": business.timezone})
    return _text(f"unknown tool: {name}", True)


def handle(session: Session, business: Business, message: Any, now_local: datetime, now_utc: datetime,
           notes: Notes) -> dict | None:
    """One JSON-RPC message → the reply (None for a notification)."""
    if isinstance(message, dict) and "method" not in message and ("result" in message or "error" in message):
        return None  # a client's response to a request of ours: we send none, nothing to answer
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _rpc(message.get("id") if isinstance(message, dict) else None, error=(-32600, "invalid request"))
    method, id_ = message["method"], message.get("id")
    if id_ is None:  # a notification (notifications/initialized, …)
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _rpc(id_, {"protocolVersion": asked if asked in SUPPORTED else SUPPORTED[0],
                          "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER,
                          "instructions": f"Tools for {business.name}: prices, free times and booking. "
                                          "Always ask the customer's name and phone before booking."})
    if method == "ping":
        return _rpc(id_, {})
    if method == "tools/list":
        return _rpc(id_, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not isinstance(name, str) or name not in {t["name"] for t in TOOLS}:
            return _rpc(id_, error=(-32602, f"unknown tool: {name}"))
        return _rpc(id_, call(session, business, name, args, now_local, now_utc, notes))
    return _rpc(id_, error=(-32601, f"method not found: {method}"))
