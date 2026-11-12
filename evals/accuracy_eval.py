"""Accuracy, rerun, and latency: crawl held-out test sites and compare with the answer key.

Built and debugged on seed 0; the published numbers use seeds 100-104, which the
code never saw while it was being written (like keeping the exam paper away from
the practice papers).
"""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scraper.config import Settings  # noqa: E402
from scraper.crawler import crawl  # noqa: E402
from scraper.profiles import get_profile  # noqa: E402
from scraper.report import percentile  # noqa: E402
from scraper.storage import Store  # noqa: E402
from testsite import pages  # noqa: E402
from testsite.generator import answer_key, generate  # noqa: E402
from testsite.server import TestSite  # noqa: E402

SEEDS = [100, 101, 102, 103, 104]
FIELDS = ("upc", "title", "category", "price_pence", "rating", "in_stock", "stock_count", "description")
FAST = replace(Settings(), min_delay_s=0.0)  # local server only: never use 0 on a real site
BOOKS = get_profile("books")


def score_seed(seed: int, n_books: int = 1000) -> dict:
    with TestSite(seed=seed, n_books=n_books) as site:
        store = Store(":memory:")
        start = site.base + "/catalogue/page-1.html"
        t0 = time.perf_counter()
        first = crawl(start, BOOKS, store, FAST)
        crawl_s = time.perf_counter() - t0
        log1 = list(site.log)

        key = answer_key(site.books, site.host)
        stored = {r["url"]: dict(r) for r in store.conn.execute("SELECT * FROM books")}
        rejected = {r[0] for r in store.conn.execute("SELECT url FROM rejects")}
        good = {u: v for u, v in key.items() if v}
        bad = {u for u, v in key.items() if v is None}
        fields_right = fields_total = books_exact = 0
        wrong_examples = []
        for url, expected in good.items():
            row = stored.get(url)
            exact = row is not None
            for f in FIELDS:
                fields_total += 1
                got = row[f] if row else None
                if f == "in_stock" and got is not None:
                    got = bool(got)
                if row is not None and got == expected[f]:
                    fields_right += 1
                else:
                    exact = False
                    if len(wrong_examples) < 5:
                        wrong_examples.append({"url": url, "field": f, "expected": expected[f], "got": got})
            books_exact += exact
        latencies = [r[0] for r in store.conn.execute(
            "SELECT elapsed_ms FROM fetch_log WHERE outcome = 'ok' AND attempts = 1")]
        bytes1 = sum(e["bytes"] for e in log1)

        # rerun with nothing changed: conditional GETs should make it nearly free
        site.reset_log(hits=False)  # same faults don't fire twice: measure the rerun itself
        t0 = time.perf_counter()
        second = crawl(start, BOOKS, store, FAST)
        rerun_s = time.perf_counter() - t0
        bytes2 = sum(e["bytes"] for e in site.log)

        # the site changes some prices: we should find exactly those
        old_prices = {b.path: b.price_pence for b in site.books}
        old_stock = {b.path: b.stock for b in site.books}
        site.set_version(2)
        third = crawl(start, BOOKS, store, FAST)
        visible = [b for b in site.books if not b.broken and b.link != "hidden"]
        planted_price = {site.base + b.path for b in visible if b.price_pence != old_prices[b.path]}
        # Only changes a reader of the page could see. A count that moves behind a page that
        # just says "In stock" is invisible. (The first version counted those and reported
        # 166/171 "found": an eval bug, not a scraper bug.)
        def shown(stock, show_count):
            return (stock > 0, stock if (show_count and stock > 0) else (0 if stock == 0 else None))
        planted_stock = {site.base + b.path for b in visible
                         if shown(b.stock, b.show_count) != shown(old_stock[b.path], b.show_count)}
        found_price = {r[0] for r in store.conn.execute(
            "SELECT url FROM changes WHERE run_id = ? AND field = 'price_pence'", (third.run_id,))}
        found_stock = {r[0] for r in store.conn.execute(
            "SELECT DISTINCT url FROM changes WHERE run_id = ? AND field IN ('stock_count', 'in_stock')",
            (third.run_id,))}

        return {
            "seed": seed,
            "books_expected": len(good),
            "books_stored": len(stored),
            "books_missing": len(set(good) - set(stored)),
            "books_extra": len(set(stored) - set(good)),
            "books_exact": books_exact,
            "fields_right": fields_right,
            "fields_total": fields_total,
            "bad_pages": len(bad),
            "bad_rejected": len(bad & rejected),
            "good_rejected": len(rejected - bad),
            "disallowed_requests": sum(e["path"].startswith(("/catalogue/hidden/", "/admin/")) for e in log1),
            "requests_first": len(log1),
            "retries_first": store.conn.execute(
                "SELECT SUM(retries) FROM fetch_log WHERE run_id = ?", (first.run_id,)).fetchone()[0],
            "bytes_first": bytes1,
            "crawl_s": round(crawl_s, 2),
            "rerun_s": round(rerun_s, 2),
            "rerun_bytes": bytes2,
            "rerun_not_modified": second.outcomes.get("not_modified", 0),
            "rerun_requests": sum(second.outcomes.values()),
            "rerun_changed": second.changed + second.new,
            "price_planted": len(planted_price),
            "price_found": len(found_price),
            "price_true_positive": len(planted_price & found_price),
            "stock_planted": len(planted_stock),
            "stock_true_positive": len(planted_stock & found_stock),
            "stock_found": len(found_stock),
            "latencies_ms": latencies,
            "wrong_examples": wrong_examples,
        }


def parse_timing(n: int = 1000) -> dict:
    """How long BeautifulSoup + our selectors take per page, network excluded."""
    books = generate(7, n)
    bodies = [pages.product_page(b, 3).encode() for b in books]
    times = []
    for body in bodies:
        t0 = time.perf_counter()
        BOOKS.parse_item(body, None, "http://x/")
        times.append((time.perf_counter() - t0) * 1000)
    listing = pages.listing_page(books, 1).encode()
    lt = []
    for _ in range(200):
        t0 = time.perf_counter()
        BOOKS.parse_listing(listing, None, "http://x/catalogue/page-1.html")
        lt.append((time.perf_counter() - t0) * 1000)
    return {"item_p50_ms": round(percentile(times, 50), 2), "item_p95_ms": round(percentile(times, 95), 2),
            "listing_p50_ms": round(percentile(lt, 50), 2), "listing_p95_ms": round(percentile(lt, 95), 2)}


def run() -> dict:
    per_seed = [score_seed(s) for s in SEEDS]
    lat = [x for s in per_seed for x in s["latencies_ms"]]
    for s in per_seed:
        s.pop("latencies_ms")
    total = {k: sum(s[k] for s in per_seed) for k in per_seed[0] if isinstance(per_seed[0][k], (int, float))
             and k != "seed"}
    requests_per_book = total["requests_first"] / total["books_stored"]
    return {
        "seeds": SEEDS,
        "totals": total,
        "per_seed": per_seed,
        "fetch_latency_ms": {"p50": round(percentile(lat, 50), 2), "p95": round(percentile(lat, 95), 2),
                             "samples": len(lat)},
        "parse": parse_timing(),
        "crawl_s_median": statistics.median(s["crawl_s"] for s in per_seed),
        "rerun_s_median": statistics.median(s["rerun_s"] for s in per_seed),
        "requests_per_book": round(requests_per_book, 3),
        "polite_minutes_per_1000_books": round(total["requests_first"] / len(SEEDS) * 1.0 / 60, 1),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2))
