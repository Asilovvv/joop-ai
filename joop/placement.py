"""Placement tests for training centres.

The school supplies its own questions (CSV) and level scale; code grades the answers, never the model.
The AI only hands out a personal link and, after the test, offers groups of the level the code computed.
"""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .lang import is_kyrgyz_message
from .niches import get_pack
from .models import Booking, Business, Conversation, Message, PlacementAttempt, PlacementQuestion, PlacementTest

GRACE = timedelta(minutes=2)  # slow networks: a submission this late is still on time
MAX_QUESTIONS = 200
MAX_OPTIONS = 6
LETTERS = "ABCDEF"
CYR_LETTERS = "АБВГДЕ"
_DIGITS = re.compile(r"\D")


def enabled(business: Business) -> bool:
    """Packs switch the module on with `features: [level_test]` (training centres, driving schools)."""
    return get_pack(business.niche).offers("level_test")


def new_code() -> str:
    return secrets.token_hex(4)


def new_token() -> str:
    return secrets.token_hex(8)  # hex only: survives the Latin/Cyrillic text fixes applied to replies


# --- scale and questions -----------------------------------------------------------------------

_BAND = re.compile(r"^\s*(\d{1,4})\s*[-–—]\s*(\d{1,4})\s*[:=]?\s*(\S.{0,40}?)\s*$")


def parse_scale(text: str) -> tuple[list[tuple[int, int, str]], list[str]]:
    """'0-10 A1' per line -> [(0, 10, 'A1'), ...] sorted by the lower bound, plus error messages."""
    bands, errors = [], []
    for n, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        m = _BAND.match(line)
        if not m or int(m.group(1)) > int(m.group(2)):
            errors.append(f"Строка {n}: «{line.strip()[:40]}» — нужен вид «0-10 A1».")
            continue
        bands.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    bands.sort()
    return bands, errors


def level_for(scale_text: str, score: int) -> str:
    for low, high, label in parse_scale(scale_text)[0]:
        if low <= score <= high:
            return label
    return ""


def _correct_index(value: str, options: list[str]) -> int | None:
    v = value.strip()
    if v.isdigit() and 1 <= int(v) <= len(options):
        return int(v) - 1
    up = v.upper()
    if len(up) == 1 and up in LETTERS[: len(options)]:
        return LETTERS.index(up)
    if len(up) == 1 and up in CYR_LETTERS[: len(options)]:
        return CYR_LETTERS.index(up)
    for i, option in enumerate(options):
        if v.casefold() == option.casefold():
            return i
    return None


def parse_questions(text: str) -> tuple[list[dict], list[str]]:
    """CSV rows 'section; question; option 1; ...; right answer' -> question dicts and error messages.

    The right answer is the option's number (1, 2...), letter (A, B... or А, Б...) or exact text.
    A header row (first cell "раздел"/"section") is skipped. Delimiter: ';', ',' or tab.
    """
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return [], ["Вставьте вопросы."]
    first = text.split("\n", 1)[0]
    delimiter = max((";", "\t", ","), key=first.count)
    questions, errors = [], []
    for n, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
        cells = [c.strip() for c in row]
        while cells and not cells[-1]:
            cells.pop()
        if not cells:
            continue
        if n == 1 and cells[0].casefold() in {"раздел", "section", "бөлүм"}:
            continue
        if len(cells) < 5:
            errors.append(f"Строка {n}: нужно минимум раздел, вопрос, два варианта и правильный ответ.")
            continue
        section, question, options, answer = cells[0][:60], cells[1][:500], [o[:200] for o in cells[2:-1] if o], cells[-1]
        if not question or len(options) < 2 or len(options) > MAX_OPTIONS:
            errors.append(f"Строка {n}: вариантов должно быть от 2 до {MAX_OPTIONS}.")
            continue
        correct = _correct_index(answer, options)
        if correct is None:
            errors.append(f"Строка {n}: правильный ответ «{answer[:30]}» не совпадает ни с одним вариантом.")
            continue
        questions.append({"section": section, "text": question, "options": options, "correct": correct})
        if len(questions) >= MAX_QUESTIONS:
            errors.append(f"Загружено первых {MAX_QUESTIONS} вопросов, остальные пропущены.")
            break
    return questions, errors


def replace_questions(session: Session, test: PlacementTest, questions: list[dict]) -> None:
    for old in session.exec(select(PlacementQuestion).where(PlacementQuestion.test_id == test.id)).all():
        session.delete(old)
    for i, q in enumerate(questions):
        session.add(PlacementQuestion(business_id=test.business_id, test_id=test.id, section=q["section"], text=q["text"],
                                      options_json=json.dumps(q["options"], ensure_ascii=False), correct=q["correct"], sort=i))


def questions_of(session: Session, test_id: int) -> list[PlacementQuestion]:
    return list(session.exec(select(PlacementQuestion).where(PlacementQuestion.test_id == test_id)
                             .order_by(PlacementQuestion.sort, PlacementQuestion.id)).all())


def options(q: PlacementQuestion) -> list[str]:
    return json.loads(q.options_json or "[]")


# --- taking the test ---------------------------------------------------------------------------


def grade(questions: list[PlacementQuestion], answers: dict[int, int]) -> tuple[int, int, dict[str, list[int]]]:
    """answers: question id -> chosen option index. Returns score, max score and per-section [right, total]."""
    score, sections = 0, {}
    for q in questions:
        right = answers.get(q.id) == q.correct
        score += right
        cell = sections.setdefault(q.section or "Тест", [0, 0])
        cell[0] += right
        cell[1] += 1
    return score, len(questions), sections


def finish(session: Session, test: PlacementTest, attempt: PlacementAttempt, answers: dict[int, int], now: datetime) -> bool:
    """Grade and close the attempt. Returns False when it was already finished (a repeated submit)."""
    if attempt.status == "finished":
        return False
    questions = questions_of(session, test.id)
    attempt.score, attempt.max_score, sections = grade(questions, answers)
    attempt.sections_json = json.dumps(sections, ensure_ascii=False)
    attempt.answers_json = json.dumps({str(k): v for k, v in answers.items()})
    attempt.level = level_for(test.scale_text, attempt.score)
    started = attempt.started_at or now
    attempt.late = bool(test.minutes) and now - started > timedelta(minutes=test.minutes) + GRACE
    attempt.status, attempt.finished_at = "finished", now
    session.add(attempt)
    return True


def sections(attempt: PlacementAttempt) -> dict[str, list[int]]:
    return json.loads(attempt.sections_json or "{}")


def _sections_line(attempt: PlacementAttempt) -> str:
    parts = sections(attempt)
    return "; ".join(f"{name} {r}/{t}" for name, (r, t) in parts.items()) if len(parts) > 1 else ""


def result_text(test: PlacementTest, attempt: PlacementAttempt, kyrgyz: bool = False) -> str:
    """The message the customer gets in their chat."""
    by = _sections_line(attempt)
    if kyrgyz:
        out = f"«{test.title}» тестинин жыйынтыгы: {attempt.max_score} суроодон {attempt.score} туура"
        out += f", деңгээлиңиз — {attempt.level}." if attempt.level else "."
        if by:
            out += f" Бөлүмдөр боюнча: {by}."
        return out + " Ушул деңгээлдеги топту тандап, сабакка жазып коёюнбу?"
    out = f"Результат теста «{test.title}»: {attempt.score} из {attempt.max_score}"
    out += f", уровень {attempt.level}." if attempt.level else "."
    if by:
        out += f" По разделам: {by}."
    return out + " Подобрать группу вашего уровня и записать на занятие?"


def admin_note(test: PlacementTest, attempt: PlacementAttempt) -> str:
    who = ", ".join(x for x in (attempt.name, attempt.phone) if x) or "без контакта"
    out = f"Тест «{test.title}» пройден: {who} — {attempt.score} из {attempt.max_score}"
    out += f", уровень {attempt.level}" if attempt.level else ""
    if attempt.late:
        out += " (сдан после лимита времени)"
    by = _sections_line(attempt)
    return out + (f". {by}" if by else "") + "."


def last_customer_text(session: Session, conversation_id: int) -> str:
    m = session.exec(select(Message).where(Message.conversation_id == conversation_id, Message.role == "customer")
                     .order_by(Message.id.desc())).first()
    return m.text if m else ""


# --- the AI side -------------------------------------------------------------------------------


def active_tests(session: Session, business_id: int) -> list[PlacementTest]:
    tests = session.exec(select(PlacementTest).where(PlacementTest.business_id == business_id, PlacementTest.active == True)  # noqa: E712
                         .order_by(PlacementTest.id)).all()
    return [t for t in tests if session.exec(select(PlacementQuestion.id).where(PlacementQuestion.test_id == t.id)).first()]


def invite(session: Session, test: PlacementTest, conv: Conversation) -> PlacementAttempt:
    """The personal attempt for this chat: reused until it is finished, so one chat gets one link."""
    attempt = session.exec(select(PlacementAttempt).where(PlacementAttempt.test_id == test.id,
                                                          PlacementAttempt.conversation_id == conv.id,
                                                          PlacementAttempt.status != "finished")).first()
    if attempt is None:
        attempt = PlacementAttempt(business_id=test.business_id, test_id=test.id, token=new_token(), conversation_id=conv.id,
                                   name=conv.customer_name, phone=conv.customer_phone)
        session.add(attempt)
        session.flush()
    return attempt


def prompt_hint(session: Session, business: Business, conv: Conversation, base_url: str) -> str:
    """Facts for the system prompt: personal test links and this customer's finished results."""
    if not enabled(business) or not base_url or conv.id is None:
        return ""
    tests = active_tests(session, business.id)
    if not tests:
        return ""
    lines = ["", "Тест на уровень (бесплатно, проверяется автоматически, результат придёт клиенту в этот чат):"]
    for t in tests:
        minutes = f", около {t.minutes} минут" if t.minutes else ""
        lines.append(f"- «{t.title}»{minutes}: ссылка для этого клиента {base_url}/t/{invite(session, t, conv).token}")
    done = session.exec(select(PlacementAttempt).where(PlacementAttempt.conversation_id == conv.id,
                                                       PlacementAttempt.status == "finished")
                        .order_by(PlacementAttempt.finished_at.desc())).all()
    titles = {t.id: t.title for t in tests}
    for a in done[:3]:
        level = f", уровень {a.level}" if a.level else ""
        lines.append(f"Клиент уже прошёл тест «{titles.get(a.test_id, 'тест')}»: {a.score} из {a.max_score}{level}.")
    lines += [
        "Если клиент хочет узнать свой уровень или записаться в группу, а его уровень неизвестен, дай ссылку на тест "
        "целиком, без изменений. Сам уровень по переписке не определяй и не угадывай.",
        "Если тест пройден, предлагай группы этого уровня (уровень указан в названии или описании группы). "
        "Если подходящей группы нет, прими заявку и скажи, что администратор подберёт группу.",
    ]
    return "\n".join(lines)


# --- report ------------------------------------------------------------------------------------


@dataclass
class TestStats:
    test: PlacementTest
    links: int  # personal links the AI sent in chats that were not opened yet
    started: int
    finished: int
    booked: int  # finished, then booked a lesson (same chat or same phone)

    @property
    def conversion(self) -> int:
        return round(100 * self.booked / self.finished) if self.finished else 0


def stats(session: Session, business_id: int) -> list[TestStats]:
    tests = session.exec(select(PlacementTest).where(PlacementTest.business_id == business_id).order_by(PlacementTest.id)).all()
    attempts = session.exec(select(PlacementAttempt).where(PlacementAttempt.business_id == business_id)).all()
    bookings = session.exec(select(Booking).where(Booking.business_id == business_id, Booking.status != "cancelled")).all()
    out = []
    for t in tests:
        mine = [a for a in attempts if a.test_id == t.id]
        finished = [a for a in mine if a.status == "finished"]
        booked = 0
        for a in finished:
            phone = _DIGITS.sub("", a.phone)[-9:]
            if any(b.created_at >= a.finished_at and ((a.conversation_id and b.conversation_id == a.conversation_id)
                                                      or (len(phone) == 9 and _DIGITS.sub("", b.customer_phone)[-9:] == phone))
                   for b in bookings):
                booked += 1
        links = sum(1 for a in mine if a.status == "invited" and a.conversation_id and session.exec(
            select(Message.id).where(Message.conversation_id == a.conversation_id, Message.role == "ai",
                                     Message.text.contains(a.token))).first())
        out.append(TestStats(test=t, links=links,
                             started=sum(a.status == "started" for a in mine), finished=len(finished), booked=booked))
    return out


def wants_kyrgyz(session: Session, attempt: PlacementAttempt) -> bool:
    return bool(attempt.conversation_id) and is_kyrgyz_message(last_customer_text(session, attempt.conversation_id))
