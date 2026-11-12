"""Per-host rate limiting: never knock on the same door faster than allowed.

Each host has a 'next allowed time'. wait() sleeps until then, then pushes the
next allowed time forward by `delay`. Different hosts don't wait for each
other. The clock and sleep are injectable so tests run instantly.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class HostRateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._clock = clock
        self._sleep = sleep
        self._next_ok: dict[str, float] = {}
        self.total_slept_s = 0.0

    def wait(self, host: str, delay: float) -> None:
        """Block until `host` may be contacted, then book the next slot."""
        now = self._clock()
        ready_at = self._next_ok.get(host, now)
        if ready_at > now:
            self._sleep(ready_at - now)
            self.total_slept_s += ready_at - now
            now = ready_at
        self._next_ok[host] = now + delay

    def pause(self, host: str, seconds: float) -> None:
        """The server said 'come back in N seconds' (Retry-After): push the slot back."""
        until = self._clock() + seconds
        self._next_ok[host] = max(self._next_ok.get(host, 0.0), until)
