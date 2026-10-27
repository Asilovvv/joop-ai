"""Business profile: loaded from YAML and rendered into the system prompt.

The profile is the single source of truth the agent may answer from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Service:
    name: str
    price: str = ""
    duration: str = ""
    note: str = ""


@dataclass
class BusinessProfile:
    name: str
    description: str
    address: str = ""
    hours: str = ""
    phone: str = ""
    languages: list[str] = field(default_factory=lambda: ["ky", "ru"])
    services: list[Service] = field(default_factory=list)
    faq: list[dict] = field(default_factory=list)
    booking_policy: str = (
        "Collect a booking request. The administrator confirms it personally."
    )
    tone: str = "Friendly, short, polite."

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BusinessProfile":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "BusinessProfile":
        if not data.get("name"):
            raise ValueError("Business profile must have a 'name'")
        services = [Service(**s) for s in data.get("services", [])]
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "services"}
        return cls(services=services, **known)

    def render(self) -> str:
        """Render the profile as plain text for the system prompt."""
        lines = [f"Business name: {self.name}", f"About: {self.description}"]
        if self.address:
            lines.append(f"Address: {self.address}")
        if self.hours:
            lines.append(f"Working hours: {self.hours}")
        if self.phone:
            lines.append(f"Phone: {self.phone}")
        if self.services:
            lines.append("Services and prices:")
            for s in self.services:
                parts = [s.name]
                if s.price:
                    parts.append(f"price: {s.price}")
                if s.duration:
                    parts.append(f"duration: {s.duration}")
                if s.note:
                    parts.append(f"note: {s.note}")
                lines.append("  - " + "; ".join(parts))
        if self.faq:
            lines.append("FAQ:")
            for item in self.faq:
                lines.append(f"  Q: {item.get('q', '')}")
                lines.append(f"  A: {item.get('a', '')}")
        lines.append(f"Booking policy: {self.booking_policy}")
        return "\n".join(lines)
