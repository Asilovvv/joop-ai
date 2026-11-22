"""Threads that answer customers, apart from the threads that serve pages.

Starlette runs every sync route and every background task in one pool of 40 threads. Answering a customer holds a
thread for as long as the model thinks, so a burst of chats took all forty and the panel waited for one: 150 chats at
once with a 3-second model, and the login page took 9 s to open. Messages from the channels, the site chat and the
demo now run here (`run`); pages keep their forty whatever the customers send.
"""

from __future__ import annotations

import asyncio
import functools
import weakref
from typing import Any, Callable, TypeVar

import anyio.to_thread
from anyio import CapacityLimiter

T = TypeVar("T")

THREADS = 40  # customers answered at the same time; the 41st waits for a free thread, pages never do
_limiters: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, CapacityLimiter] = weakref.WeakKeyDictionary()


def limiter() -> CapacityLimiter:
    """One limit per event loop: a limiter waits with the primitives of the loop it first ran in (tests start many)."""
    loop = asyncio.get_running_loop()
    found = _limiters.get(loop)
    if found is None:
        found = _limiters[loop] = CapacityLimiter(THREADS)
    return found


async def run(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """`fn(*args, **kwargs)` in a thread for customers, off the event loop."""
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs), limiter=limiter())
