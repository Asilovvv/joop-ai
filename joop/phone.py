"""Phone number normalization (Kyrgyzstan first, neighbours tolerated)."""

from __future__ import annotations

import re


def normalize_phone(raw: str | None) -> str | None:
    """Return a phone in +E.164 form, or None if it does not look like a phone number.

    0555 123 456 -> +996555123456; 555123456 -> +996555123456; 996555123456 -> +996555123456;
    8 701 123 45 67 / 7 701 ... -> +7701...; other numbers are accepted only with a leading '+'.
    """
    if not raw:
        return None
    text = raw.strip()
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if len(digits) == 12 and digits.startswith("996"):
        return "+" + digits
    if len(digits) == 10 and digits.startswith("0"):
        return "+996" + digits[1:]
    if len(digits) == 9 and not has_plus:
        return "+996" + digits
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if has_plus and 10 <= len(digits) <= 15:
        return "+" + digits
    return None
