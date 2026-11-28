"""One business never reads or changes another's rows, through any route of the server.

A check of one route at a time is written by whoever wrote the route, and says what its author thought of. This file
asks every route the same questions, including the routes added after it was written.

The victim is a business nobody signs in to: row 1 of every table, with a mark in every text a person could have
typed. The attacker is a second business with the example data and every switch on; its owner signs in to the panel
and to the app and makes an API key. The attacker's owner (panel, app, API key) and a visitor without a login call
every route. Four tests:

1. With the victim's number wherever a route takes a row's number (in the address, the query, a form, the JSON):
   no response carries the victim's mark (a name, a phone, a message, a token); no row of the victim's has changed or
   gone; no row of the attacker's points to the victim's rows or holds their text; nothing went to a messenger or to
   another server with the mark in it; and the server did not fail (a 500 on another business's number is a row read
   without asking whose it is).
2. The server does not fail on a row of the caller's own either. The attacker's row 1000 of every table points to row
   1000 of the others, as the rows of a business with some history do: a delete that forgets what points to the row
   fails here. That is how tests/test_delete_with_history.py came to be.
3. Without a login, every route answers «sign in», except the routes listed as public; and the founder's console
   answers so to a business's owner too.
4. A route that takes a row's number tells its own rows from another's: with the attacker's own row it works, with the
   victim's it refuses. Statuses alone do not show that (a panel route answers 303 either way), so «works» is also:
   it wrote for the first and not for the second, or it changed the attacker's own row. A route may hide behind the
   kind of business (orders in work exist for a repair shop, not for a dentist), so the attacker tries as every kind
   until its own row is accepted. What cannot be shown this way is read by a person and listed with the reason.

The database is put back after every call that changed it, so each call meets the same rows. About 1,800 calls, 12
seconds.

When this file fails after a change of yours: a new public route goes to PUBLIC; a route that checks a word before
it looks at the row (a status, a stage) gets a real word in WORDS; anything else it says is a hole, read it first.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
import shutil
import sqlite3
import time as clock
import types
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Union, get_args, get_origin

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlmodel import SQLModel

from joop import api, billing, db, funnel, jobs, page_booking, timeutil
from joop.config import settings_from_env
from joop.presets import create_business
from joop.web.app import create_app

from .conftest import NOW_UTC, FakeRuntime, reset_counters

MARK, DIGITS = "zzvictim", "7770001234"  # the digits survive a phone's normalisation, the word survives the rest
LEAK = re.compile(rf"{MARK}-([a-z0-9_]+?)-([a-z0-9_]+?)-{DIGITS}", re.I)
VICTIM, OWN = 1, 1000  # the row of every table that is the victim's, and the one that is the attacker's
ATTACKER, PASSWORD = "attacker", "secret-pass"

# What the victim's business row holds where a mark would stop the server before it reaches the question asked here.
PLAIN = {("business", "timezone"): "Asia/Bishkek", ("business", "niche"): "beauty", ("business", "language"): "ru"}
# Where a new row's default would make a state that does not happen. Row 1000's booking points to row 1000's time,
# which is free: that is a cancelled booking, the history every business has (tests/test_delete_with_history.py).
STATE = {("booking", "status"): "cancelled"}
NOT_OURS_COLUMNS = {"altegio_location_id", "crm_pipeline_id"}  # numbers of other systems


# --- the rows -------------------------------------------------------------------------------------------


def kind_of(col: sa.Column) -> Any:
    return getattr(col.type, "impl", col.type)  # an encrypted token is a string underneath


def is_state(col: sa.Column) -> bool:
    """A text column that holds one of the server's own words (a status, a channel), not what a person typed: it has
    a default that is not empty."""
    default = getattr(col.default, "arg", None)
    return isinstance(default, str) and default != ""


def new_row(table: sa.Table, pk: int, business_id: int, parents: set[str], text: Callable[[sa.Column], str | None]) -> dict[str, Any]:
    """A row as a new row of its kind is born: the columns' own defaults (a free time, a new request), tomorrow; STATE
    where a default would not do. The victim's and the attacker's rows differ in whose they are and in their text, in
    nothing else: a route that accepts one and refuses the other does so because of whose it is."""
    tomorrow = NOW_UTC + timedelta(days=1)
    row: dict[str, Any] = {"id": pk}
    for col in table.columns:
        kind = kind_of(col)
        if col.primary_key:
            continue
        if (table.name, col.name) in STATE:
            row[col.name] = STATE[(table.name, col.name)]
        elif col.name == "business_id":
            row[col.name] = business_id
        elif col.foreign_keys:
            parent = next(iter(col.foreign_keys)).column.table.name
            row[col.name] = pk if parent in parents else (None if col.nullable else VICTIM)
        elif isinstance(kind, sa.String) and not is_state(col) and text(col) is not None:
            row[col.name] = text(col)
        elif col.default is not None or col.nullable:
            continue  # the column's own default; nothing where nothing is the default
        elif isinstance(kind, sa.DateTime):
            row[col.name] = tomorrow
        elif isinstance(kind, sa.Date):
            row[col.name] = tomorrow.date()
        elif isinstance(kind, sa.Boolean):
            row[col.name] = False
        elif isinstance(kind, (sa.Integer, sa.Float, sa.Numeric)):
            row[col.name] = 1
        elif isinstance(kind, sa.String):
            row[col.name] = "own"
        else:
            raise AssertionError(f"{table.name}.{col.name}: a column type this test does not know ({type(col.type).__name__})")
    return row


def seed_victim() -> None:
    """Row 1 of every table: the victim business and everything that could belong to it, with a mark in every text a
    person could have typed."""
    tables = SQLModel.metadata.sorted_tables
    with db.get_engine().begin() as con:
        for table in tables:
            row = new_row(table, VICTIM, VICTIM, {t.name for t in tables},
                          lambda col, t=table: PLAIN.get((t.name, col.name), f"{MARK}-{t.name}-{col.name}-{DIGITS}"))
            con.execute(table.insert().values(row))


def seed_own(attacker_id: int) -> None:
    """Row 1000 of every table that belongs to a business: the attacker's own."""
    tables = SQLModel.metadata.sorted_tables
    owned = {t.name for t in tables if "business_id" in t.c}
    owned |= {t.name for t in tables if t.name != "business" and t.foreign_keys  # a line of an order, a delivery of a mailing
              and all(fk.column.table.name in owned for fk in t.foreign_keys)}
    with db.get_engine().begin() as con:
        for table in tables:
            if table.name not in owned:
                continue
            single = [c for c in table.columns if c.unique and c.name == "business_id"]
            if single and con.execute(sa.select(table.c.id).where(table.c.business_id == attacker_id)).first():
                continue  # one row a business (its subscription): the attacker has its own already
            con.execute(table.insert().values(new_row(table, OWN, attacker_id, owned, lambda col: f"own-{col.name}" if col.unique else None)))


def is_link(col: sa.Column) -> bool:
    """A column that names a row of ours: by the database's own rule, or by its name alone (the request an answer came
    from, the item offered with another) where the code keeps the link itself."""
    if col.primary_key:
        return False
    return bool(col.foreign_keys) or (col.name.endswith("_id") and col.name not in NOT_OURS_COLUMNS
                                      and isinstance(kind_of(col), sa.Integer))


def rows() -> dict[str, dict[int, tuple]]:
    with db.get_engine().connect() as con:
        return {t.name: {row[0]: tuple(row) for row in con.execute(sa.select(t))} for t in SQLModel.metadata.sorted_tables}


# --- what a route takes, and what to send ---------------------------------------------------------------

ROW_WORDS = {"id", "ids", "slot", "staff", "service", "room", "booking", "lead", "master", "conversation", "order", "unit"}
NOT_OURS = {"location_id", "pipeline_id", "after_id"}  # a salon in Altegio, a funnel in amoCRM, a place in a list: no row of ours
PATH_WORDS = {"what": ["bookings", "orders", "leads", "customers"]}  # /api/v1/{what}
# A word a route checks before it looks at the row: without a real one the call never reaches the question.
WORDS = {"/api/mobile/jobs/{item_id}": {"status": sorted(jobs.STATUSES)[0]}, "/panel/jobs/{item_id}": {"status": sorted(jobs.STATUSES)[0]},
         "/panel/funnel/{item_id}": {"stage": list(funnel.STAGES)[0]},
         "/panel/accounts": {"name": "Мастер", "login": "master1"}, "/api/mobile/accounts": {"name": "Мастер", "login": "master1"},
         "/m/{slug}/book": {"hp_note": "", "lang": "ru"}}


# A JSON body whose names the handler does not read itself (it hands the object on): the names, and how they are sent.
BOOKING = ["slot_id", "name", "phone", "service"]
BODIES: dict[str, tuple[list[str], Callable[[dict], Any]]] = {
    "/api/v1/bookings": (BOOKING, lambda sent: sent),
    "/mcp": (BOOKING, lambda sent: {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "book", "arguments": sent}}),
}


def is_row(name: str, annotation: Any = None) -> bool:
    """Whether an input names a row of a table: slot_id, staff_id; and slot, staff, service where they are numbers."""
    if name in NOT_OURS:
        return False
    if name.endswith(("_id", "_ids")) or name in ("id", "ids"):
        return True
    return name in ROW_WORDS and annotation in (int, None)


def text_for(name: str) -> str:
    n = name.lower()
    if "phone" in n:
        return "+996700123456"
    if n in ("date", "day", "from", "to", "since", "until", "check_in", "check_out", "night", "ready_by", "valid_until") \
            or n.endswith(("_date", "_day", "_from", "_to")):
        return "2026-11-06"
    if n in ("time", "start", "end", "at", "when") or n.endswith(("_time", "_at", "_start", "_end")):
        return "2026-11-06T10:00"
    if "password" in n:
        return PASSWORD
    if "email" in n:
        return "a@example.com"
    if "url" in n or n in ("site", "link", "website"):
        return "https://example.com"
    return "1"


def value_for(name: str, annotation: Any, row: Callable[[str], int]) -> Any:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        return value_for(name, inner[0], row) if inner else None
    if origin in (list, set, tuple):
        args = get_args(annotation)
        return [value_for(name, args[0] if args else str, row)]
    if origin is dict or annotation is dict:
        return {}
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return {k: value_for(k, f.annotation, row) for k, f in annotation.model_fields.items()}
        if issubclass(annotation, bool):
            return True
        if issubclass(annotation, int):
            return row(name) if is_row(name, int) else 1
        if issubclass(annotation, float):
            return 1.0
        if issubclass(annotation, datetime):
            return "2026-11-06T10:00:00"
        if issubclass(annotation, date):
            return "2026-11-06"
        if issubclass(annotation, time):
            return "10:00"
    return str(row(name)) if is_row(name) else text_for(name)


KEY = r"""\.(?:get|getlist|pop)\(\s*["'](\w+)["']|\[\s*["'](\w+)["']\s*\]"""


def keys_read(source: str, var: str) -> list[str]:
    """Names a handler reads from a form or a JSON object it parses itself: var.get("name"), var["name"]."""
    return sorted({a or b for a, b in re.findall(rf"\b{var}{KEY}", source)})


def row_names(annotation: Any, name: str = "") -> set[str]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType, list, set, tuple):
        return set().union(*[row_names(a, name) for a in get_args(annotation) if a is not type(None)] or [set()])
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return set().union(*[row_names(f.annotation, k) for k, f in annotation.model_fields.items()] or [set()])
    return {name} if name and is_row(name, annotation if annotation in (int, str) else None) else set()


@dataclass
class Call:
    method: str
    path: str  # the route's template
    url: str
    params: dict = field(default_factory=dict)
    data: dict | None = None
    json: Any = None
    files: dict | None = None


@dataclass
class Plan:
    """What one route takes."""

    method: str
    path: str
    path_ints: list[str]
    path_texts: dict[str, list[str]]
    query: dict[str, Any]
    form: dict[str, Any] | None
    body: tuple[str, Any] | None  # the JSON body's name and type
    body_keys: list[str]  # of a JSON object the handler reads itself
    files: list[str]

    @property
    def rows(self) -> list[str]:
        """Inputs that name a row."""
        found = set(self.path_ints) | {n for n, a in self.query.items() if is_row(n, a)}
        found |= {n for n, a in (self.form or {}).items() if is_row(n, a if a is int else None)}
        found |= {n for n in self.body_keys if is_row(n)}
        if self.body:
            found |= row_names(self.body[1])
        return sorted(found)

    def calls(self, row: Callable[[str], int], slug: str) -> list[Call]:
        words = WORDS.get(self.path, {})
        variants: list[dict[str, str]] = [{n: str(row(n)) for n in self.path_ints}]
        for name, options in self.path_texts.items():
            variants = [dict(v, **{name: o}) for v in variants for o in ([slug] if name == "slug" else options)]
        params = {n: words.get(n, value_for(n, a, row)) for n, a in self.query.items()}
        data = None if self.form is None else {n: words.get(n, str(value_for(n, a, row))) for n, a in self.form.items()}
        body = None
        if self.body:
            body = value_for(self.body[0], self.body[1], row)
            if isinstance(body, dict):
                body.update({k: v for k, v in words.items() if k in body})
        if self.body_keys:
            body = dict(body or {}, **{k: words.get(k, value_for(k, str, row)) for k in self.body_keys})
            body.update({k: [row(k)] for k in self.body_keys if k.endswith("_ids") or k == "ids"})
            body.update({k: row(k) for k in self.body_keys if self.path in BODIES and is_row(k)})  # a number, as the API says
            body = BODIES[self.path][1](body) if self.path in BODIES else body
        files = {n: ("x.txt", b"1", "text/plain") for n in self.files} or None
        out = []
        for v in variants:
            url = re.sub(r"{(\w+)(?::\w+)?}", lambda m: v[m.group(1)], self.path)
            out.append(Call(self.method, self.path, url, params, *((data, body, files) if self.method != "GET" else (None, None, None))))
        return out


def plans(app: Any) -> list[Plan]:
    found = []
    for r in app.routes:
        router = getattr(r, "original_router", None)
        for route in (router.routes if router is not None else [r]):
            if not (hasattr(route, "methods") and hasattr(route, "dependant")):
                continue
            dep, source = route.dependant, inspect.getsource(route.endpoint)
            ints = [p.name for p in dep.path_params if p.field_info.annotation is int]
            texts = {p.name: PATH_WORDS.get(p.name, ["1", DIGITS]) for p in dep.path_params if p.field_info.annotation is not int}
            form: dict[str, Any] | None = None
            body: tuple[str, Any] | None = None
            body_keys: list[str] = []
            files: list[str] = []
            for p in dep.body_params:
                info = type(p.field_info).__name__
                if info == "File" or "UploadFile" in str(p.field_info.annotation):
                    files.append(p.name)
                elif info == "Form":
                    form = dict(form or {}, **{p.name: p.field_info.annotation})
                elif p.field_info.annotation is dict or get_origin(p.field_info.annotation) is dict:
                    body_keys = keys_read(source, p.name)
                else:
                    body = (p.name, p.field_info.annotation)
            var = re.search(r"(\w+)\s*=\s*await request\.form\(\)", source)
            if var:
                form = dict(form or {}, **{k: str for k in keys_read(source, var.group(1))})
            var = re.search(r"(\w+)\s*=\s*await request\.json\(\)", source)
            if var:
                body_keys = BODIES[route.path][0] if route.path in BODIES else keys_read(source, var.group(1))
            query = {p.name: p.field_info.annotation for p in dep.query_params}
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append(Plan(method, route.path, ints, texts, query, form, body, body_keys, files))
    return found


# --- the laboratory -------------------------------------------------------------------------------------


@dataclass
class Shot:
    who: str
    call: Call
    status: int
    location: str
    wrote: bool
    found: list[str]
    touched: bool = False  # the call changed the attacker's own row 1000 of some table, or made a row point to one

    @property
    def refused(self) -> bool:
        return self.status in (401, 403, 404) or (self.status == 303 and self.location in ("/login", "/owner/login"))

    def __str__(self) -> str:
        sent = self.call.json if self.call.json is not None else self.call.data
        return (f"{self.who} {self.call.method} {self.call.url} [{self.call.path}] {self.call.params or ''} {sent or ''} "
                f"-> {self.status} {self.location}: {'; '.join(self.found)}")


class Outside:
    """Every request the server makes to another server (a messenger, a CRM): recorded and refused."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(f"{request.method} {request.url} {request.content[:2000]!r}")
        return httpx.Response(503, json={"ok": False})


class Lab:
    """The server with the victim and the attacker in it, and the people who call it."""

    def __init__(self, tmp: Path, settings: Any) -> None:
        self.tmp, self.path = tmp, Path(db.get_engine().url.database)
        seed_victim()
        self.victim = {t: kept[VICTIM] for t, kept in rows().items()}
        with db.new_session() as s:
            b = create_business(s, slug=ATTACKER, name="Attacker", password=PASSWORD, demo=True, now_utc=NOW_UTC)
            for col in SQLModel.metadata.tables["business"].columns:  # every switch on: the online page, booking by a link, the API
                if isinstance(col.type, sa.Boolean):
                    setattr(b, col.name, True)
            self.api_key = api.new_key(b)
            s.add(b)
            billing.start_trial(s, b, 14, NOW_UTC)  # the public pages of a business work while it may use the product
            s.commit()
            self.attacker_id = b.id
        self.rt, self.secret = FakeRuntime(settings), settings.session_secret
        self.outside = Outside()
        self.rt.http = httpx.Client(transport=httpx.MockTransport(self.outside))
        self.app = create_app(settings, self.rt, init=False)
        self.plans = plans(self.app)
        self.clients = {who: TestClient(self.app, raise_server_exceptions=False) for who in ("owner", "app", "key", "nobody")}
        panel = self.clients["owner"]
        csrf = re.search(r'name="csrf" value="([^"]+)"', panel.get("/login").text).group(1)
        r = panel.post("/login", data={"slug": ATTACKER, "password": PASSWORD, "csrf": csrf}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/panel", (r.status_code, r.text[:200])
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', panel.get("/panel").text).group(1)
        self.cookies = dict(panel.cookies)
        token = self.clients["app"].post("/api/mobile/login", json={"company": ATTACKER, "password": PASSWORD, "user": ""}).json()["token"]
        self.headers = {"owner": {}, "app": {"Authorization": f"Bearer {token}"}, "key": {"Authorization": f"Bearer {self.api_key}"}, "nobody": {}}
        self.images: dict[str, tuple[Path, dict]] = {}
        self.current = self.save("plain")
        seed_own(self.attacker_id)
        self.save("own")
        self.put("plain")

    def save(self, name: str) -> str:
        db.get_engine().dispose()  # the last connection writes the journal into the file: the copy is whole
        file = self.tmp / f"{name}.db"
        shutil.copyfile(self.path, file)
        self.images[name] = (file, rows())
        assert all(self.images[name][1][t][VICTIM] == kept for t, kept in self.victim.items()), "setting up changed the victim"
        return name

    def put(self, name: str) -> None:
        db.get_engine().dispose()
        for suffix in ("-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        shutil.copyfile(self.images[name][0], self.path)
        self.current = name

    def as_kind(self, niche: str) -> str:
        """The image with the attacker's own rows, the attacker being a business of this kind."""
        name = f"own-{niche}"
        if name not in self.images:
            self.put("own")
            with db.get_engine().begin() as con:
                t = SQLModel.metadata.tables["business"]
                con.execute(t.update().where(t.c.id == self.attacker_id).values(niche=niche))
            self.save(name)
        return name

    def shoot(self, who: str, call: Call, image: str) -> Shot:
        if self.current != image:
            self.put(image)
        reset_counters()
        client = self.clients[who]
        client.cookies.clear()
        if who == "owner":
            client.cookies.update(self.cookies)
        kwargs: dict[str, Any] = {"params": call.params, "headers": self.headers[who], "follow_redirects": False}
        if call.method != "GET":
            if call.json is not None:
                kwargs["json"] = call.json
            else:
                data = dict(call.data or {}, csrf=self.csrf) if who == "owner" else dict(call.data or {})
                if call.path == "/m/{slug}/book":  # the page signs its form for the time it showed, a minute ago here
                    data["t"] = page_booking.form_token(self.secret, self.attacker_id, int(data["slot"]), int(clock.time()) - 60)
                kwargs.update(data=data, files=call.files)
        senders = (self.rt.tg, self.rt.wa, self.rt.ig)
        mark = [len(x.sent) for x in senders], len(self.outside.seen)
        watch = sqlite3.connect(self.path)
        before = watch.execute("PRAGMA data_version").fetchone()[0]
        r = client.request(call.method, call.url, **kwargs)
        wrote = watch.execute("PRAGMA data_version").fetchone()[0] != before
        watch.close()
        found: list[str] = []
        leaked = sorted({f"{t}.{c}".lower() for t, c in LEAK.findall(r.text)})
        if leaked:
            found.append("shown: " + ", ".join(leaked))
        elif MARK in r.text.lower() or DIGITS in r.text:
            found.append("shown: the mark, changed on the way")
        if r.status_code >= 500:
            found.append("the server failed")
        lines = [f"{chat} {text}" for x, n in zip(senders, mark[0]) for chat, text in x.sent[n:]] + self.outside.seen[mark[1]:]
        found += [f"sent: {line[:160]}" for line in lines if MARK in line.lower() or DIGITS in line]
        touched = False
        if wrote:
            damage, touched = self.damage(image)
            found += damage
            self.put(image)
        return Shot(who, call, r.status_code, r.headers.get("location", ""), wrote, found, touched)

    def damage(self, image: str) -> tuple[list[str], bool]:
        """What the call did to the victim's rows, and whether it did anything to the attacker's own row 1000."""
        found, touched, was, now = [], False, self.images[image][1], rows()
        for t, table in SQLModel.metadata.tables.items():
            names = [c.name for c in table.columns]
            if now[t].get(VICTIM) != self.victim[t]:
                changed = [n for n, a, b in zip(names, self.victim[t], now[t].get(VICTIM) or ()) if a != b]
                found.append(f"changed: {t} ({', '.join(changed) if now[t].get(VICTIM) else 'gone'})")
            touched = touched or now[t].get(OWN) != was[t].get(OWN)
            links = [i for i, c in enumerate(table.columns) if is_link(c)]
            for pk, row in now[t].items():
                old = was[t].get(pk)
                if pk == VICTIM or row == old:
                    continue
                refs = [names[i] for i in links if row[i] == VICTIM and (old is None or old[i] != VICTIM)]
                if refs:
                    found.append(f"points to the victim: {t} #{pk} ({', '.join(refs)})")
                copied = [n for n, v in zip(names, row) if isinstance(v, str) and (MARK in v.lower() or DIGITS in v)]
                if copied:
                    found.append(f"copied from the victim: {t} #{pk} ({', '.join(copied)})")
                touched = touched or any(row[i] == OWN and (old is None or old[i] != OWN) for i in links)
        return found, touched

    def close(self) -> None:
        for client in self.clients.values():
            client.close()


@pytest.fixture(scope="module")
def lab(tmp_path_factory, migrated_db):
    """A fixture of the module is set up before the fixtures of a test, so it freezes the clock and builds the
    settings itself."""
    tmp = tmp_path_factory.mktemp("isolation")
    shutil.copyfile(migrated_db, tmp / "test.db")
    eng = db.make_engine(f"sqlite:///{tmp / 'test.db'}")
    db.set_engine(eng)
    settings = dataclasses.replace(
        settings_from_env(), database_url="sqlite://", meta_verify_token="verify-me", meta_app_secret="app-secret",
        public_base_url="https://joop.test", scheduler_enabled=False, anthropic_api_key="", llm_provider="anthropic",
        llm_base_url="", llm_api_key="")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(timeutil, "clock", lambda: NOW_UTC)
        made = Lab(tmp, settings)
        try:
            yield made
        finally:
            made.close()
            eng.dispose()
            db.set_engine(None)


@pytest.fixture(scope="module")
def shots(lab) -> list[Shot]:
    """Every route, by everyone, with the victim's number wherever a number goes."""
    return [lab.shoot(who, call, "plain") for plan in lab.plans for call in plan.calls(lambda _name: VICTIM, ATTACKER)
            for who in lab.clients]


@dataclass
class Verdict:
    """One input of one route that names a row, called by one person."""

    who: str
    plan: Plan
    name: str
    kind: str  # the kind of business the attacker was when its own row was accepted, or "" when it never was
    own: Shot  # the call with the attacker's own row in every such input
    theirs: Shot  # the same call with the victim's row in this input

    @property
    def proven(self) -> bool:
        """The route told the two rows apart: it accepted the attacker's own and refused the victim's; or it wrote for
        the first and not for the second; or it did something to the attacker's own row, and (the first test of this
        file) nothing to the victim's."""
        if self.own.refused:
            return False
        return self.theirs.refused or (self.own.wrote and not self.theirs.wrote) or self.own.touched

    def __str__(self) -> str:
        return (f"{self.who} {self.plan.method} {self.plan.path} · {self.name}: own row -> {self.own.status} {self.own.location}"
                f"{' (wrote)' if self.own.wrote else ''}, victim's -> {self.theirs.status} {self.theirs.location}"
                f"{' (wrote)' if self.theirs.wrote else ''}{' as ' + self.kind if self.kind else ''}")


@pytest.fixture(scope="module")
def verdicts(lab) -> list[Verdict]:
    from joop.niches import all_packs

    first = "dental"
    kinds = [first] + sorted(k for k in all_packs() if k != first)
    found = []
    for plan in lab.plans:
        for who in lab.clients if plan.rows else ():
            kind, own = "", None
            for k in kinds:
                shot = lab.shoot(who, plan.calls(lambda _name: OWN, ATTACKER)[0], lab.as_kind(k))
                own = own or shot
                if not shot.refused:
                    kind, own = k, shot
                    break
                if shot.status != 404:
                    break  # a login wall, not a kind of business: no other kind opens it
            for name in plan.rows:
                call = plan.calls(lambda n, name=name: VICTIM if n == name else OWN, ATTACKER)[0]
                found.append(Verdict(who, plan, name, kind, own, lab.shoot(who, call, lab.as_kind(kind or first))))
    return found


# Routes that answer a visitor without a login with something other than «sign in». A new one is added here on
# purpose, or it gets a login. Pages and files of the site; a business's public pages by its address; what is opened by
# a secret in the address (a booking made on the page, a partner's page, a level test); sign-up; and routes that check
# their caller another way and say so before anything else (a payment provider's signature, an API key, JSON-RPC).
PUBLIC = {
    "GET /", "GET /vozmozhnosti", "GET /privacy", "GET /data-deletion", "GET /offline", "GET /sw.js", "GET /health",
    "GET /login", "GET /signup", "GET /audit", "GET /studio", "GET /owner/login", "POST /owner/login",
    "GET /ai/{slug}", "GET /site/{slug}", "GET /r/{code}", "GET /partner/{secret}", "GET /t/{token}", "GET /test/{code}",
    "GET /c/{slug}", "POST /c/{slug}/chat", "GET /c/{slug}/updates", "GET /c/{slug}/widget.js",
    "GET /m/{slug}", "GET /m/{slug}/qr.svg", "GET /m/{slug}/book", "POST /m/{slug}/book", "GET /m/{slug}/book/{token}",
    "GET /m/{slug}/book/{token}/booking.ics",
    "GET /api/mobile/niches", "GET /api/mobile/places/{slug}", "POST /api/mobile/signup",
    "POST /billing/freedompay/result", "GET /mcp",
}
# An input that names a row, on a route that does not show by its answer or by what it writes whose row it took:
# read and found safe, with the reason.
REVIEWED = {
    "GET /m/{slug}/book · slot": "the time is looked up among the business's own free times; another's shows the list again",
    "GET /m/{slug}/book · staff": "a filter of the business's own free times",
}


def test_nothing_of_another_business_is_shown_changed_or_sent(shots, verdicts):
    assert len(shots) > 900 and len({s.call.path for s in shots}) > 200  # the survey saw the server, not an empty app
    found = [str(s) for s in shots if s.found] + [str(v.theirs) for v in verdicts if v.theirs.found]
    assert not found, "\n".join(found)


def test_the_server_does_not_fail_on_a_row_of_the_callers_own(verdicts):
    """Row 1000 of every table points to row 1000 of the others, as rows of a business with some history do. A delete
    that forgets what points to the row fails here (tests/test_delete_with_history.py)."""
    found = sorted({str(v.own) for v in verdicts if v.own.found})
    assert not found, "\n".join(found)


def test_without_a_login_every_route_says_sign_in(shots):
    def wall(s: Shot) -> bool:
        return s.status in (401, 403) or (s.status == 303 and s.location in ("/login", "/owner/login"))

    open_to_all = {f"{s.call.method} {s.call.path}" for s in shots if s.who == "nobody" and not wall(s)}
    assert open_to_all == PUBLIC, f"new: {sorted(open_to_all - PUBLIC)}; no longer open: {sorted(PUBLIC - open_to_all)}"
    # the founder's console is nobody's but the founder's: not a business's owner's either
    console = [str(s) for s in shots if s.call.path.startswith("/owner") and f"{s.call.method} {s.call.path}" not in PUBLIC and not wall(s)]
    assert not console, "\n".join(console)
    # and the people of the survey are who they say: each opens what is theirs
    mine = {s.who: s.status for s in shots if (s.who, s.call.method, s.call.path) in (
        ("owner", "GET", "/panel/bookings"), ("app", "GET", "/api/mobile/me"), ("key", "GET", "/api/v1/slots"))}
    assert mine == {"owner": 200, "app": 200, "key": 200}


def test_a_route_that_takes_a_row_tells_its_own_from_anothers(verdicts):
    inputs: dict[str, list[Verdict]] = {}
    for v in verdicts:
        inputs.setdefault(f"{v.plan.method} {v.plan.path} · {v.name}", []).append(v)
    assert len(inputs) > 80  # the survey found the inputs that name rows
    unproven = {}
    for name, group in inputs.items():
        if any(v.proven for v in group):
            continue
        if all(v.own.refused and v.own.status != 404 for v in group) and group[0].plan.path.startswith("/owner"):
            continue  # the founder's console: nobody of the survey gets in (the test above)
        unproven[name] = "; ".join(str(v) for v in group if not v.own.refused) or "its own row is never accepted: " + str(group[0])
    new = {name: why for name, why in unproven.items() if name not in REVIEWED}
    assert not new, ("these do not show that they tell their own row from another's (a word the route checks first goes to WORDS; "
                     "a route read and found safe, to REVIEWED):\n" + "\n".join(f"{name}: {why}" for name, why in new.items()))
    assert set(REVIEWED) <= set(unproven), f"proven now, take out of REVIEWED: {sorted(set(REVIEWED) - set(unproven))}"
