"""robots.txt: the site's own rules about what bots may fetch.

Our own parser and matcher, written against RFC 9309 (the robots.txt standard),
instead of Python's urllib.robotparser. Why: the gold set showed the stdlib's
behaviour depends on the Python version. On 3.11 and 3.12 it uses the first
matching rule instead of the longest and ignores * and $ wildcards, so it fetched
pages the site had disallowed. On 3.13 it still read a file starting with a UTF-8
BOM as having no rules, and ignored 'Crawl-delay: 2.5'. Politeness shouldn't
depend on which Python you happen to run.

What the HTTP status of /robots.txt means (RFC 9309 section 2.3.1):
    2xx            -> parse the file and obey it
    4xx (incl 404) -> no rules: everything allowed
    5xx / no reply -> assume the worst: nothing allowed
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

# fetch_text(url) -> (status, text); status 0 means "network error"
FetchText = Callable[[str], tuple[int, str]]

# Characters left as-is when normalising percent-encoding, so '/%7Ejoe/' == '/~joe/'
_SAFE = "/?=&*$:@!+,;~-._'()"


def _canonical(path: str) -> str:
    return quote(unquote(path), safe=_SAFE)


@dataclass
class Rule:
    allow: bool
    pattern: str  # canonical form, e.g. '/catalogue/*.pdf$'
    regex: re.Pattern = field(init=False, repr=False)

    def __post_init__(self):
        anchored = self.pattern.endswith("$")
        body = self.pattern[:-1] if anchored else self.pattern
        # '*' = any run of characters; everything else literal; '$' at the end = end of URL
        self.regex = re.compile(".*".join(re.escape(part) for part in body.split("*"))
                                + ("$" if anchored else ""), re.DOTALL)

    def matches(self, path: str) -> bool:
        return self.regex.match(path) is not None


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)  # lower-case product tokens, or '*'
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def parse_groups(text: str) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    last_was_agent = False
    for raw in text.lstrip("﻿").splitlines():  # a leading BOM is not part of the first line
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:  # consecutive UA lines share one group
                current = Group()
                groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if current is None:
            continue  # rules before any User-agent line belong to nobody
        if key in ("allow", "disallow") and value:  # an empty value is "no rule"
            current.rules.append(Rule(allow=key == "allow", pattern=_canonical(value)))
        elif key == "crawl-delay":
            try:
                current.crawl_delay = max(0.0, float(value))
            except ValueError:
                pass
    return groups


def product_token(user_agent: str) -> str:
    """'web-scraper/0.1 (+https://...)' -> 'web-scraper'."""
    return user_agent.split("/", 1)[0].split(" ", 1)[0].strip().lower()


@dataclass
class RobotsPolicy:
    allow_all: bool = False
    disallow_all: bool = False
    groups: list[Group] = field(default_factory=list)
    status: int = 0

    def _groups_for(self, user_agent: str) -> list[Group]:
        """RFC 9309 2.2.1: groups naming our token (merged); otherwise the '*' groups."""
        token = product_token(user_agent)
        mine = [g for g in self.groups if token in g.agents]
        return mine or [g for g in self.groups if "*" in g.agents]

    def allowed(self, url: str, user_agent: str) -> bool:
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        if self.allow_all or parts.path == "/robots.txt":
            return True
        target = _canonical(parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: Rule | None = None
        for group in self._groups_for(user_agent):
            for rule in group.rules:
                if rule.matches(target):
                    longer = best is None or len(rule.pattern) > len(best.pattern)
                    tie_allow = best is not None and len(rule.pattern) == len(best.pattern) and rule.allow
                    if longer or tie_allow:  # longest match wins; on a tie, Allow wins
                        best = rule
        return True if best is None else best.allow

    def crawl_delay(self, user_agent: str) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(user_agent) if g.crawl_delay is not None]
        return max(delays) if delays else None


def parse_robots(status: int, text: str) -> RobotsPolicy:
    if 200 <= status < 300:
        return RobotsPolicy(groups=parse_groups(text), status=status)
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
