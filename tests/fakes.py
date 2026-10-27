"""Fake LLM client that replays scripted responses (no network)."""

from __future__ import annotations

from types import SimpleNamespace


def text(t: str):
    return SimpleNamespace(type="text", text=t)


def tool(name: str, args: dict, id_: str = "tu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


def response(*blocks, stop_reason: str | None = None):
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self  # mimic client.messages.create

    async def create(self, **kwargs):
        # deep-ish copy of messages so later mutation doesn't change the record
        kwargs = dict(kwargs)
        kwargs["messages"] = [dict(m) for m in kwargs["messages"]]
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeLLM: no scripted responses left")
        return self._responses.pop(0)
