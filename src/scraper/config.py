"""Every knob the scraper has, in one frozen dataclass.

The defaults are the polite, safe settings. The `guard_*` switches exist so the
attack eval can turn one defence off at a time and prove it was doing something
(an "ablation"). Never turn them off for a real crawl.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DEFAULT_USER_AGENT = (
    "web-scraper/0.1 (+https://github.com/paulmadojutimi94/web-scraper; learning project)"
)


@dataclass(frozen=True)
class Settings:
    # --- identity -----------------------------------------------------------
    user_agent: str = DEFAULT_USER_AGENT

    # --- politeness -----------------------------------------------------------
    min_delay_s: float = 1.0  # minimum gap between two requests to the same host
    respect_robots: bool = True  # obey robots.txt Allow/Disallow
    honor_crawl_delay: bool = True  # robots.txt Crawl-delay can make us slower, never faster
    honor_retry_after: bool = True  # a 429/503 Retry-After header pauses the whole host
    max_retry_after_s: float = 120.0  # ...but a hostile server can't park us forever

    # --- robustness -----------------------------------------------------------
    timeout_s: float | None = 10.0  # connect + read timeout per attempt (None = wait forever)
    guard_total_time: bool = True  # timeout_s also caps the whole body download, not just each read
    max_retries: int = 3  # extra attempts after the first, for 429 / 5xx / network errors
    backoff_base_s: float = 0.5  # 0.5s, 1s, 2s ... plus jitter
    max_bytes: int | None = 5_000_000  # refuse bodies bigger than this (None = no limit)
    max_redirects: int = 5
    max_pages: int = 5_000  # hard cap on fetches in one run, whatever the site does

    # --- efficiency -----------------------------------------------------------
    use_cache: bool = True  # conditional GET: send ETag / Last-Modified, accept 304

    # --- defences (attack-eval ablation switches) -----------------------------
    guard_scope: bool = True  # only http(s), only the start host, checked on every redirect hop
    guard_visited: bool = True  # never fetch the same listing page twice (pagination loops)
    guard_no_progress: bool = True  # stop paginating when a page adds no new items
    check_content_type: bool = True  # only parse text/html
    escape_html: bool = True  # HTML report escapes scraped text
    guard_formulas: bool = True  # CSV export defuses leading = + - @

    def as_dict(self) -> dict:
        return asdict(self)
