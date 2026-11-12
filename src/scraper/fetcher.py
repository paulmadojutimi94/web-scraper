"""HTTP fetching: polite, bounded, and honest about what happened.

One call to Fetcher.fetch(url) does, in order, for every redirect hop:
  1. scope check   - http(s) only, start host only
  2. robots check  - is this path allowed for our user agent?
  3. rate limit    - wait our turn for this host
  4. GET           - conditional (ETag / Last-Modified) if we've seen it before
  5. bounded read  - stop at max_bytes, stop at the total time limit
  6. retry         - 429 / 5xx / network error: back off (honouring Retry-After), try again
and returns a FetchResult whose `outcome` says exactly what happened.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

import requests

from .config import Settings
from .ratelimit import HostRateLimiter
from .robots import RobotsCache
from .urls import host_of, in_scope, normalize

RETRY_STATUSES = {429, 500, 502, 503, 504}
HTML_TYPES = ("text/html", "application/xhtml+xml")


class Cache(Protocol):
    def cache_get(self, url: str) -> CachedPage | None: ...
    def cache_put(self, url: str, page: CachedPage) -> None: ...


@dataclass
class CachedPage:
    body: bytes
    encoding: str | None
    etag: str | None
    last_modified: str | None


@dataclass
class FetchResult:
    url: str
    final_url: str
    outcome: str  # ok | not_modified | robots_blocked | out_of_scope | http_error |
    #               network_error | too_large | not_html | too_many_redirects
    status: int = 0
    body: bytes = b""
    encoding: str | None = None
    attempts: int = 0  # HTTP requests sent, across retries and redirect hops
    retries: int = 0  # attempts repeated because of 429 / 5xx / network errors
    redirects: int = 0
    elapsed_ms: float = 0.0  # time spent on the network, not waiting our turn
    bytes_received: int = 0
    error: str | None = None
    location: str | None = None  # set only on a 3xx: where the server sent us

    @property
    def ok(self) -> bool:
        return self.outcome in ("ok", "not_modified")


class _BodyTooLargeError(Exception):
    pass


class _TooSlowError(Exception):
    pass


def charset_from_content_type(content_type: str) -> str | None:
    """'text/html; charset=UTF-8' -> 'utf-8'. No charset -> None (let the parser sniff).

    Deliberately NOT requests' response.encoding, which falls back to ISO-8859-1
    for any text/* without a charset. That fallback is why so many scrapers of
    books.toscrape.com print 'Â£51.77' instead of '£51.77'.
    """
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip("\"' ").lower()
    return None


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Retry-After is either seconds ('120') or an HTTP date. Returns seconds, or None."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return max(0.0, (when - now).total_seconds())


class Fetcher:
    def __init__(
        self,
        settings: Settings,
        start_url: str,
        cache: Cache | None = None,
        session: requests.Session | None = None,
        limiter: HostRateLimiter | None = None,
        rng: random.Random | None = None,
    ):
        self.s = settings
        self.allowed_host = host_of(normalize(start_url))
        self.cache = cache if settings.use_cache else None
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml"}
        )
        self.limiter = limiter or HostRateLimiter()
        self.rng = rng or random.Random(0)  # seeded jitter: runs are repeatable
        self.robots = RobotsCache(self._fetch_robots_text, settings.user_agent)

    # -- robots.txt ---------------------------------------------------------------
    def _fetch_robots_text(self, url: str) -> tuple[int, str]:
        self.limiter.wait(host_of(url), self.s.min_delay_s)
        try:
            self.limiter.mark_sent(host_of(url))
            resp = self.session.get(url, timeout=self.s.timeout_s, allow_redirects=True)
        except requests.RequestException:
            return 0, ""
        return resp.status_code, resp.text[:500_000]  # RFC 9309: parse at least 500 KiB

    def _delay_for(self, url: str) -> float:
        delay = self.s.min_delay_s
        if self.s.respect_robots and self.s.honor_crawl_delay:
            crawl_delay = self.robots.crawl_delay(url)
            if crawl_delay is not None:
                delay = max(delay, crawl_delay)  # robots can slow us down, never speed us up
        return delay

    # -- public -----------------------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        url = normalize(url)
        current = url
        attempts = retries = 0
        elapsed = 0.0
        for hop in range(self.s.max_redirects + 1):
            if self.s.guard_scope and not in_scope(current, self.allowed_host):
                return FetchResult(url, current, "out_of_scope", attempts=attempts, elapsed_ms=elapsed)
            if self.s.respect_robots and not self.robots.allowed(current):
                return FetchResult(url, current, "robots_blocked", attempts=attempts, elapsed_ms=elapsed)

            result = self._get_with_retries(url, current)
            attempts += result.attempts
            retries += result.attempts - 1
            elapsed += result.elapsed_ms
            result.attempts, result.retries, result.elapsed_ms = attempts, retries, elapsed
            result.redirects = hop

            if result.location:  # 3xx: go round again with the new URL, re-checking scope + robots
                current = normalize(result.location, current)
                continue
            return result
        return FetchResult(url, current, "too_many_redirects", attempts=attempts, retries=retries,
                           redirects=self.s.max_redirects + 1, elapsed_ms=elapsed)

    # -- one URL, with retries --------------------------------------------------------
    def _get_with_retries(self, url: str, current: str) -> FetchResult:
        host = host_of(current)
        cached = self.cache.cache_get(current) if self.cache else None
        headers = {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        elapsed = 0.0
        last_error = ""
        for attempt in range(1, self.s.max_retries + 2):
            self.limiter.wait(host, self._delay_for(current))
            started = time.perf_counter()
            try:
                resp, body = self._get_bounded(current, headers, started)
            except _BodyTooLargeError:
                elapsed += (time.perf_counter() - started) * 1000
                return FetchResult(url, current, "too_large", attempts=attempt, elapsed_ms=elapsed,
                                   error=f"body over {self.s.max_bytes} bytes")
            except (requests.ConnectionError, requests.Timeout, _TooSlowError) as exc:
                elapsed += (time.perf_counter() - started) * 1000
                last_error = f"{type(exc).__name__}: {exc}"[:300]
                if attempt <= self.s.max_retries:
                    self.limiter.pause(host, self._backoff(attempt))
                    continue
                return FetchResult(url, current, "network_error", attempts=attempt,
                                   elapsed_ms=elapsed, error=last_error)
            except requests.RequestException as exc:  # bad URL, unsupported scheme...: don't retry
                elapsed += (time.perf_counter() - started) * 1000
                return FetchResult(url, current, "network_error", attempts=attempt,
                                   elapsed_ms=elapsed, error=f"{type(exc).__name__}: {exc}"[:300])
            elapsed += (time.perf_counter() - started) * 1000
            status = resp.status_code

            if status in RETRY_STATUSES and attempt <= self.s.max_retries:
                wait = self._backoff(attempt)
                if self.s.honor_retry_after:
                    retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                    if retry_after is not None:
                        wait = max(wait, min(retry_after, self.s.max_retry_after_s))
                self.limiter.pause(host, wait)
                continue

            result = FetchResult(url, current, "ok", status=status, attempts=attempt,
                                 elapsed_ms=elapsed, bytes_received=len(body))
            if 300 <= status < 400 and status != 304:
                location = resp.headers.get("Location")
                if location:
                    result.location = location
                    return result
                result.outcome, result.error = "http_error", "redirect without Location"
                return result
            if status == 304 and cached:
                result.outcome, result.body, result.encoding = "not_modified", cached.body, cached.encoding
                return result
            if status != 200:
                result.outcome = "http_error"
                return result

            content_type = resp.headers.get("Content-Type", "")
            if self.s.check_content_type and not content_type.lower().startswith(HTML_TYPES):
                result.outcome, result.error = "not_html", content_type[:100]
                return result
            result.body, result.encoding = body, charset_from_content_type(content_type)
            if self.cache and (resp.headers.get("ETag") or resp.headers.get("Last-Modified")):
                self.cache.cache_put(current, CachedPage(body, result.encoding,
                                                         resp.headers.get("ETag"),
                                                         resp.headers.get("Last-Modified")))
            return result
        return FetchResult(url, current, "http_error", attempts=self.s.max_retries + 1,
                           elapsed_ms=elapsed, error=last_error or "retries exhausted")

    def _get_bounded(self, url: str, headers: dict, started: float) -> tuple[requests.Response, bytes]:
        """GET without following redirects; read at most max_bytes within timeout_s in total."""
        self.limiter.mark_sent(host_of(url))
        resp = self.session.get(url, headers=headers, timeout=self.s.timeout_s,
                                allow_redirects=False, stream=True)
        try:
            limit = self.s.max_bytes
            declared = resp.headers.get("Content-Length", "")
            if limit is not None and declared.isdigit() and int(declared) > limit:
                raise _BodyTooLargeError  # don't even start reading
            chunks, total = [], 0
            while True:
                # read1 returns as soon as *any* bytes arrive. iter_content(65536) would
                # block until it had 64 KiB, so a server dripping one byte every 0.25s
                # kept us waiting the full 6s and the deadline check below never ran.
                chunk = resp.raw.read1(65536, decode_content=True)
                if not chunk:
                    break
                total += len(chunk)
                if limit is not None and total > limit:
                    raise _BodyTooLargeError
                # requests' timeout is per read, so a server dripping one byte a second
                # never trips it. This is the total-time limit.
                if (self.s.guard_total_time and self.s.timeout_s is not None
                        and time.perf_counter() - started > self.s.timeout_s):
                    raise _TooSlowError(f"body still arriving after {self.s.timeout_s}s")
                chunks.append(chunk)
            return resp, b"".join(chunks)
        finally:
            resp.close()

    def _backoff(self, attempt: int) -> float:
        """0.5s, 1s, 2s, 4s ... each scaled by a random 0.5x-1.5x so clients don't retry in lockstep."""
        return self.s.backoff_base_s * (2 ** (attempt - 1)) * (0.5 + self.rng.random())
