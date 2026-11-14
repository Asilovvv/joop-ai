"""Prescription medicines (pharmacies): the code, not the model, decides how they may be reserved.

A pack switches it on with ``features: [prescription]``. An item is a prescription medicine when its category or note
says «по рецепту», «рецептурный», «Rx» or «рецепт менен» (not «без рецепта» or «не по рецепту»). Such an item is never delivered: an order with it and delivery is
refused with the reason, and a pickup reservation carries «покажите рецепт» to the customer and the staff. The
model never decides whether a prescription is needed; the pharmacy marks it in its catalog.
"""

from __future__ import annotations

from .models import Service

import re

MARK = "по рецепту"
# «по рецепту», «Рецептурный», «Rx», «рецепт менен» — in any case and spacing; «без рецепта», «не по рецепту» are not.
_RX = re.compile(r"(?<!не )(?<!без )(?:по рецепту|рецептурн\w*|\brx\b|рецепт менен)", re.IGNORECASE)
NO_DELIVERY = ("«{names}» отпускается только по рецепту в аптеке: доставить не можем. "
               "Можем отложить для самовывоза — рецепт покажите при получении.")
SHOW_PRESCRIPTION = "При получении покажите рецепт на: {names}."


def _marked(text: str) -> bool:
    return bool(_RX.search(" ".join((text or "").split()).lower()))  # collapses NBSP, tabs and double spaces


def is_rx(item: Service) -> bool:
    return _marked(item.category) or _marked(item.note)


def check(items: list[Service], mode: str) -> tuple[str, str]:
    """(refusal, note): a refusal when the order cannot be placed as asked; a note for a valid order with prescription items."""
    names = ", ".join(dict.fromkeys(i.name for i in items if is_rx(i)))
    if not names:
        return "", ""
    if mode == "delivery":
        return NO_DELIVERY.format(names=names), ""
    return "", SHOW_PRESCRIPTION.format(names=names)
