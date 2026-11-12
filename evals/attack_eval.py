"""Attack eval: 14 hostile pages, each trying to make the scraper misbehave.

Every attack has a success check that looks at hard evidence (the server log,
the database, the report files). Then, for each defence that has an off switch,
we turn it off and re-run its attacks: if the attack now succeeds, the defence
was really the thing stopping it. 0% with every defence on means little on its
own; the ablation is what proves the attacks were real.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scraper.config import Settings  # noqa: E402
from scraper.crawler import crawl  # noqa: E402
from scraper.profiles import get_profile  # noqa: E402
from scraper.report import build_summary, write_reports  # noqa: E402
from scraper.storage import Store  # noqa: E402
from testsite.server import PAYLOADS, TestSite  # noqa: E402

BASE_SETTINGS = replace(Settings(), min_delay_s=0.0, backoff_base_s=0.1, timeout_s=1.0,
                        max_retries=1, max_pages=40)


@dataclass
class Evidence:
    log: list
    store: Store
    out: Path


def _listing_paths(ev):
    return [e["path"] for e in ev.log if "/page-" in e["path"]]


def _per_attempt_ms(ev, name):
    rows = ev.store.conn.execute("SELECT elapsed_ms, attempts FROM fetch_log WHERE url LIKE ?",
                                 (f"%/hostile/{name}/item%",)).fetchall()
    return max((r[0] / max(r[1], 1) for r in rows), default=0)


def _csv_cells(ev):
    with (ev.out / "books.csv").open(encoding="utf-8-sig") as fh:
        return [c for row in csv.reader(fh) for c in row]


def _gap(ev, path):
    hits = sorted(e["t"] for e in ev.log if e["path"] == path)
    return hits[1] - hits[0] if len(hits) > 1 else None


# name, what it tries, defence switch (None = no off switch), succeeded(evidence) -> bool
ATTACKS = [
    ("robots", "link to a page robots.txt disallows", {"respect_robots": False},
     lambda ev: any(e["path"] == "/admin/secret.html" for e in ev.log)),
    ("loop", "page 3's 'next' points back to page 1", {"guard_visited": False},
     lambda ev: len(_listing_paths(ev)) != len(set(_listing_paths(ev)))),
    ("endless", "'next' forever, same items on every page", {"guard_no_progress": False},
     lambda ev: len(_listing_paths(ev)) > 3),
    ("redirect", "item redirects to another host (SSRF-style)", {"guard_scope": False},
     lambda ev: any((e["host"] or "").startswith("localhost") for e in ev.log)),
    ("bomb", "20 MB response with no Content-Length", {"max_bytes": None},
     lambda ev: ev.store.conn.execute("SELECT MAX(bytes) FROM fetch_log").fetchone()[0] > 5_000_000),
    ("slow", "server says nothing for 3 s", {"timeout_s": None},
     lambda ev: _per_attempt_ms(ev, "slow") > 2500),
    ("drip", "headers at once, then 1 byte every 0.25 s", {"guard_total_time": False},
     lambda ev: _per_attempt_ms(ev, "drip") > 2500),
    ("retryafter", "429 with Retry-After: 2", {"honor_retry_after": False},
     lambda ev: (_gap(ev, "/hostile/retryafter/item.html") or 99) < 1.9),
    ("notHtml", "an image/png that contains a book page", {"check_content_type": False},
     lambda ev: ev.store.conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] > 0),
    ("xss", "title is a <script> tag", {"escape_html": False},
     lambda ev: PAYLOADS["xss"] in (ev.out / "report.html").read_text()),
    ("formula", "title is an Excel formula", {"guard_formulas": False},
     lambda ev: any(c.startswith(("=", "+", "-", "@")) for c in _csv_cells(ev))),
    ("sqli", "title is a SQL injection", None,
     lambda ev: ev.store.conn.execute(
         "SELECT COUNT(*) FROM books WHERE title = ?", (PAYLOADS["sqli"],)).fetchone()[0] != 1),
    ("honeypot", "hidden link only a naive crawler follows", None,
     lambda ev: any("trap" in e["path"] for e in ev.log)),
    ("storm", "item answers 503 forever", None,
     lambda ev: sum(e["path"] == "/hostile/storm/item.html" for e in ev.log) > BASE_SETTINGS.max_retries + 1),
]


def attempt(site: TestSite, name: str, settings: Settings) -> bool:
    site.reset_log()
    store = Store(":memory:")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        try:
            crawl(f"{site.base}/hostile/{name}/page-1.html", get_profile("books"), store, settings)
            write_reports(build_summary(store.conn), out, settings)
        except Exception as exc:  # the scraper crashing is a successful attack too
            print(f"  {name}: scraper crashed: {type(exc).__name__}: {exc}")
            return True
        check = next(a[3] for a in ATTACKS if a[0] == name)
        try:
            return bool(check(Evidence(list(site.log), store, out)))
        except Exception as exc:  # e.g. the books table was dropped
            print(f"  {name}: check raised {type(exc).__name__}: {exc} -> counted as success")
            return True


def run() -> dict:
    results = []
    with TestSite(seed=1, n_books=20) as site:
        for name, what, defence, _check in ATTACKS:
            defended = attempt(site, name, BASE_SETTINGS)
            ablated = None
            if defence:
                ablated = attempt(site, name, replace(BASE_SETTINGS, **defence))
            off = ", ".join(f"{k}={v}" for k, v in defence.items()) if defence else None
            results.append({"attack": name, "what": what, "defence_off": off,
                            "succeeded_with_defences": defended, "succeeded_with_defence_off": ablated})
    return {"attacks": results,
            "success_with_defences": sum(r["succeeded_with_defences"] for r in results),
            "total": len(results),
            "ablated": sum(r["defence_off"] is not None for r in results),
            "success_with_defence_off": sum(bool(r["succeeded_with_defence_off"]) for r in results)}


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2))
