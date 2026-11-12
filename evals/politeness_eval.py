"""Politeness, measured from the server's side of the conversation.

The server logs every request it receives. From that log alone we check:
  - the gap between two requests is never shorter than our delay
  - a robots.txt Crawl-delay longer than our delay is obeyed
  - Retry-After is obeyed
  - nothing robots.txt disallows is ever requested
  - every request carries our User-Agent
"""

from __future__ import annotations

import multiprocessing
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import requests  # noqa: E402

from scraper.config import Settings  # noqa: E402
from scraper.crawler import crawl  # noqa: E402
from scraper.fetcher import Fetcher  # noqa: E402
from scraper.profiles import get_profile  # noqa: E402
from scraper.storage import Store  # noqa: E402
from testsite.generator import generate  # noqa: E402
from testsite.server import TestSite  # noqa: E402

CLIENT_TOLERANCE_S = 0.0005  # the limiter decides on this side: only clock-read overhead allowed
SERVER_TOLERANCE_S = 0.020  # the server timestamps when its handler thread starts: that jitters


def gaps(log: list[dict]) -> list[float]:
    times = sorted(e["t"] for e in log)
    return [b - a for a, b in zip(times, times[1:], strict=False)]


def _serve(conn, kwargs) -> None:
    """Child process: run the test site, report its port, hand back the log when told to stop."""
    site = TestSite(**kwargs).start()
    conn.send(site.port)
    conn.recv()
    conn.send(list(site.log))
    site.stop()


def one(delay: float, crawl_delay: float | None, n_books: int = 60) -> dict:
    # The server runs in its own process. In the same process, its threads compete with the
    # scraper for Python's GIL and add milliseconds of jitter to both sides' timestamps.
    parent, child = multiprocessing.Pipe()
    proc = multiprocessing.Process(target=_serve, args=(child, {"seed": 11, "n_books": n_books,
                                                                "crawl_delay": crawl_delay}))
    proc.start()
    try:
        port = parent.recv()
        base = f"http://127.0.0.1:{port}"
        settings = replace(Settings(), min_delay_s=delay, backoff_base_s=0.05)
        session = requests.Session()
        sent: list[dict] = []
        original_get = session.get

        def timed_get(*args, **kwargs):  # timestamp the moment each request leaves
            sent.append({"t": time.monotonic(), "url": args[0] if args else kwargs.get("url")})
            return original_get(*args, **kwargs)

        session.get = timed_get
        start = base + "/catalogue/page-1.html"
        fetcher = Fetcher(settings, start, session=session)
        crawl(start, get_profile("books"), Store(":memory:"), settings, fetcher=fetcher)
        parent.send("stop")
        log = parent.recv()
    finally:
        proc.join(timeout=10)
    expected = max(delay, crawl_delay or 0)
    g = gaps(log)
    cg = gaps(sent)
    retry_after_gaps = []
    for b in generate(11, n_books):  # same seed as the server: same books, same planted faults
        if b.fault == "429" and b.link != "hidden":
            hits = sorted(e["t"] for e in log if e["path"] == b.path)
            if len(hits) >= 2:
                retry_after_gaps.append(hits[1] - hits[0])
    return {
        "delay_s": delay,
        "crawl_delay_s": crawl_delay,
        "required_gap_s": expected,
        "requests": len(log),
        "client_min_gap_s": round(min(cg), 4),
        "client_gaps_too_short": sum(x < expected - CLIENT_TOLERANCE_S for x in cg),
        "server_min_gap_s": round(min(g), 4),
        "server_gaps_too_short": sum(x < expected - SERVER_TOLERANCE_S for x in g),
        "disallowed_requests": sum(e["path"].startswith(("/admin/", "/catalogue/hidden/")) for e in log),
        "wrong_user_agent": sum(e["ua"] != settings.user_agent for e in log),
        "retry_after_cases": len(retry_after_gaps),
        "retry_after_violations": sum(x < 1.0 - SERVER_TOLERANCE_S for x in retry_after_gaps),
    }


def run() -> dict:
    cases = [one(0.2, None), one(0.1, 0.3), one(0.5, 0.25, n_books=30), one(0.2, None, n_books=400)]
    return {"cases": cases,
            "total_requests": sum(c["requests"] for c in cases),
            "client_gaps_too_short": sum(c["client_gaps_too_short"] for c in cases),
            "server_gaps_too_short": sum(c["server_gaps_too_short"] for c in cases),
            "client_min_shortfall_ms": round(max(0.0, max(1000 * (c["required_gap_s"] - c["client_min_gap_s"])
                                                          for c in cases)), 1),
            "server_min_shortfall_ms": round(max(1000 * (c["required_gap_s"] - c["server_min_gap_s"])
                                                 for c in cases), 1),
            "disallowed_requests": sum(c["disallowed_requests"] for c in cases),
            "wrong_user_agent": sum(c["wrong_user_agent"] for c in cases)}


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2))
