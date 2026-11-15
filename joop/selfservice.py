"""A customer cancels or moves their own booking in the chat, and the AI does it instead of passing it to staff.

«Не смогу прийти завтра, перенесите на четверг» used to become a request for staff: someone read it, moved the
booking by hand and wrote back, often hours later, and the time stayed taken meanwhile. Now the AI sees the
customer's upcoming bookings from this chat, offers free times as for a new booking, and when the customer has
chosen it answers with `change`; code checks it and does it through joop/reschedule.py, the same as the panel's
«Перенести» and «Отменить». Staff get a note; a freed time goes to the waiting list (dispatch.deliver).

What is never done here, and goes to staff instead:
- a booking not made from this chat: a phone number someone types opens nothing;
- a visit less than NOTICE ahead: close to the time the clinic may want to talk to the customer;
- a booking kept in Altegio (moved there), and cancelling a visit with a prepayment (the money is staff's to return);
- anything for a business that turned it off (Business.self_service): such requests go to staff as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from .confirm import fmt_slot_ky
from .models import Booking, Business, Conversation, Slot
from .niches import get_pack
from .reschedule import cancel, move
from .slots import lead_for
from .timeutil import fmt_slot

NOTICE = timedelta(hours=2)
LISTED = 5  # upcoming bookings of one chat shown to the model

RULE = ("Записи клиента из этого чата перечислены выше с номерами. Если клиент просит отменить или перенести одну из них "
        "и до неё больше двух часов, сделай это сам, а не через администратора. Перенос: предложи 2–3 свободных времени "
        "из списка окон; когда клиент выбрал, заполни change: booking_id — номер записи, action \"move\", slot_id — номер "
        "окна. Отмена: когда клиент ясно попросил отменить, заполни change с action \"cancel\" и slot_id null. Если записей "
        "несколько и непонятно, о какой речь, уточни. В reply не подтверждай перенос или отмену сам: система допишет "
        "результат. Если до записи меньше двух часов или клиент хочет вернуть предоплату — передай администратору (handoff).")


def enabled(business: Business) -> bool:
    return business.self_service and get_pack(business.niche).has("booking")


def own_bookings(s: Session, business: Business, conv: Conversation, now_local: datetime) -> list[Booking]:
    """The chat's upcoming bookings the AI may change; empty when the business turned it off."""
    if not enabled(business):
        return []
    return list(s.exec(select(Booking).where(
        Booking.business_id == business.id, Booking.conversation_id == conv.id, Booking.status == "booked",
        Booking.start > now_local, Booking.slot_id != None,  # noqa: E711  (a request without a time is not a booking yet)
    ).order_by(Booking.start).limit(LISTED)).all())


def prompt_lines(bookings: list[Booking]) -> list[str]:
    if not bookings:
        return []
    lines = ["", "Записи клиента из этого чата (номер записи: день и время — специалист, услуга):"]
    for b in bookings:
        what = ", ".join(x for x in (b.staff_name, b.service) if x)
        lines.append(f"- запись {b.id}: {fmt_slot(b.start)}" + (f" — {what}" if what else ""))
    return lines


@dataclass
class Done:
    reply: str
    note: str = ""  # for staff, when something changed
    handoff: str = ""  # for staff, when it could not be done here
    freed: Slot | None = None  # a time given back, for the waiting list
    changed: Booking | None = None


def _words(kyrgyz: bool) -> dict[str, str]:
    if kyrgyz:
        return {"staff": "Өтүнүчүңүздү администраторго бердим, ал сиз менен байланышат.",
                "other": "Бул убакыт азыр бош эмес. Тизмеден башка убакытты тандаңызчы."}
    return {"staff": "Передала вашу просьбу администратору, он свяжется с вами.",
            "other": "Это время уже недоступно. Выберите, пожалуйста, другое из свободных."}


def apply(s: Session, business: Business, conv: Conversation, change: dict, now_local: datetime, kyrgyz: bool,
          hidden_staff: set[int] | frozenset[int] = frozenset()) -> Done:
    """Do what `change` asks, if the rules allow; otherwise say so and leave it to staff. The caller commits."""
    words = _words(kyrgyz)
    booking = s.get(Booking, change["booking_id"])
    action = change["action"]
    if booking is None or booking.business_id != business.id or booking.conversation_id != conv.id \
            or booking.status != "booked" or not enabled(business):
        who = ", ".join(x for x in (conv.customer_name, conv.customer_phone) if x) or "клиент"
        return Done(words["staff"], handoff=f"Клиент просит {'отменить' if action == 'cancel' else 'перенести'} запись "
                                            f"({who}), но такой записи из этого чата нет. Проверьте и свяжитесь с клиентом.")
    when = f"{fmt_slot(booking.start)}" + (f", {booking.staff_name}" if booking.staff_name else "")
    who = ", ".join(x for x in (booking.customer_name, booking.customer_phone) if x) or "клиент"
    asked = "отменить" if action == "cancel" else "перенести"

    def to_staff(why: str) -> Done:
        return Done(words["staff"], handoff=f"Клиент просит {asked} запись {when} ({who}): {why} Свяжитесь с клиентом.")

    if booking.start <= now_local + NOTICE:
        return to_staff("до визита меньше двух часов, ИИ такое не меняет.")
    if booking.external_id:
        return to_staff("запись в Altegio — измените её там.")
    if action == "cancel" and booking.deposit_status == "paid":
        return to_staff("по записи получена предоплата — решите, как её вернуть.")

    if action == "cancel":
        done, freed = cancel(s, booking)
        if not done:
            return to_staff("запись уже изменили.")
        text = (f"Жазылууңузду ({fmt_slot_ky(booking.start)}) жокко чыгардым. Башка убакытка келгиңиз келсе, жазыңыз."
                if kyrgyz else f"Отменила вашу запись на {fmt_slot(booking.start)}. Если захотите прийти в другое время — напишите.")
        return Done(text, note=f"Клиент сам отменил запись через ИИ: {who}, {when}.", freed=freed, changed=booking)

    slot = s.get(Slot, change["slot_id"]) if change.get("slot_id") else None
    if slot is None or slot.business_id != business.id \
            or slot.start <= now_local + timedelta(minutes=lead_for(business)):  # what the AI may offer at all
        return Done(words["other"])
    old_when = when
    moved = move(s, business, booking, slot, now_local, hidden_staff)
    if moved.problem:
        if moved.problem.startswith(("Это время уже занято", "Такого времени нет", "Это то же самое время")):
            return Done(words["other"])  # the customer picks another time from the list
        return to_staff(moved.problem)
    name = moved.member.name if moved.member else booking.staff_name
    text = (f"Даяр: жазылууңузду {fmt_slot_ky(slot.start)} убакытка жылдырдым ({name}). Күтөбүз!" if kyrgyz
            else f"Готово: перенесла вашу запись на {fmt_slot(slot.start)} ({name}). Ждём вас!")
    return Done(text, note=f"Клиент сам перенёс запись через ИИ: {who}, {old_when} → {fmt_slot(slot.start)}, {name}.",
                freed=moved.old, changed=booking)
