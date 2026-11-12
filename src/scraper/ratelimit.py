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
        self._last: dict[str, float] = {}  # when we last contacted each host
        self._paused_until: dict[str, float] = {}  # Retry-After / backoff
        self.total_slept_s = 0.0

    def wait(self, host: str, delay: float) -> None:
        """Block until `host` may be contacted, then record the contact.

        The gap is measured from the *last request* using the delay known *now*.
        (The first version booked the next slot in advance with the delay known
        then, so the request right after robots.txt ignored the Crawl-delay that
        robots.txt had just announced. The politeness eval caught it.)
        """
        now = self._clock()
        ready_at = max(self._last.get(host, float("-inf")) + delay,
                       self._paused_until.get(host, float("-inf")))
        if ready_at > now:
            self._sleep(ready_at - now)
            self.total_slept_s += ready_at - now
            now = ready_at
        self._last[host] = now

    def pause(self, host: str, seconds: float) -> None:
        """The server said 'come back in N seconds' (Retry-After): nothing before then."""
        until = self._clock() + seconds
        self._paused_until[host] = max(self._paused_until.get(host, float("-inf")), until)

    def mark_sent(self, host: str) -> None:
        """Call at the instant a request goes out. The gap is then measured send-to-send,
        even if something (a GC pause, another thread) delayed us after wait() returned."""
        self._last[host] = max(self._last.get(host, float("-inf")), self._clock())
