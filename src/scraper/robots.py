"""robots.txt: the site's own rules about what bots may fetch.

Fetched once per host and cached for the run. What the HTTP status means
follows RFC 9309 (the robots.txt standard), section 2.3.1:

    2xx            -> parse the file and obey it
    4xx (incl 404) -> no rules: everything allowed
    5xx / no reply -> assume the worst: nothing allowed

Python's own urllib.robotparser treats 401/403 as "disallow everything",
which is stricter than the RFC; here we follow the RFC.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

# fetch_text(url) -> (status, text); status 0 means "network error"
FetchText = Callable[[str], tuple[int, str]]


@dataclass
class RobotsPolicy:
    allow_all: bool = False
    disallow_all: bool = False
    parser: RobotFileParser | None = None
    status: int = 0

    def allowed(self, url: str, user_agent: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all or self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)

    def crawl_delay(self, user_agent: str) -> float | None:
        if self.parser is None:
            return None
        delay = self.parser.crawl_delay(user_agent)
        return float(delay) if delay is not None else None


def parse_robots(status: int, text: str) -> RobotsPolicy:
    if 200 <= status < 300:
        rp = RobotFileParser()
        rp.parse(text.splitlines())
        return RobotsPolicy(parser=rp, status=status)
    if 400 <= status < 500:
        return RobotsPolicy(allow_all=True, status=status)
    return RobotsPolicy(disallow_all=True, status=status)  # 5xx or unreachable


class RobotsCache:
    """One RobotsPolicy per host, fetched the first time we need it."""

    def __init__(self, fetch_text: FetchText, user_agent: str):
        self._fetch_text = fetch_text
        self._user_agent = user_agent
        self._policies: dict[str, RobotsPolicy] = {}

    def policy_for(self, url: str) -> RobotsPolicy:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key not in self._policies:
            status, text = self._fetch_text(f"{key}/robots.txt")
            self._policies[key] = parse_robots(status, text)
        return self._policies[key]

    def allowed(self, url: str) -> bool:
        return self.policy_for(url).allowed(url, self._user_agent)

    def crawl_delay(self, url: str) -> float | None:
        return self.policy_for(url).crawl_delay(self._user_agent)
