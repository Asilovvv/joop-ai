"""Prescription medicines (pharmacies): the code, not the model, decides how they may be reserved.

A pack switches it on with ``features: [prescription]``. An item is a prescription medicine when its category is
«по рецепту» or its note says «по рецепту». Such an item is never delivered: an order with it and delivery is
refused with the reason, and a pickup reservation carries «покажите рецепт» to the customer and the staff. The
model never decides whether a prescription is needed; the pharmacy marks it in its catalog.
"""

from __future__ import annotations

from .models import Service

MARK = "по рецепту"
NO_DELIVERY = ("«{names}» отпускается только по рецепту в аптеке: доставить не можем. "
               "Можем отложить для самовывоза — рецепт покажите при получении.")
SHOW_PRESCRIPTION = "При получении покажите рецепт на: {names}."


def is_rx(item: Service) -> bool:
    return MARK in (item.category or "").lower() or MARK in (item.note or "").lower()


def check(items: list[Service], mode: str) -> tuple[str, str]:
    """(refusal, note): a refusal when the order cannot be placed as asked; a note for a valid order with prescription items."""
    names = ", ".join(dict.fromkeys(i.name for i in items if is_rx(i)))
    if not names:
        return "", ""
    if mode == "delivery":
        return NO_DELIVERY.format(names=names), ""
    return "", SHOW_PRESCRIPTION.format(names=names)
