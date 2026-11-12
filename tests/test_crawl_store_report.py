import csv
import json
from dataclasses import replace

from scraper.cli import main
from scraper.crawler import crawl
from scraper.profiles import get_profile
from scraper.report import build_summary, defuse, percentile, render_html, write_reports
from scraper.storage import Store
from testsite.generator import answer_key

BOOKS = get_profile("books")


def _stored(store):
    return {r["url"]: dict(r) for r in store.conn.execute("SELECT * FROM books")}


def test_full_crawl_matches_answer_key(site, fast):
    store = Store(":memory:")
    stats = crawl(site.base + "/catalogue/page-1.html", BOOKS, store, fast)
    assert stats.stop_reason == "done" and stats.listing_pages == 3
    key = answer_key(site.books, site.host)
    stored = _stored(store)
    assert set(stored) == {u for u, v in key.items() if v}
    for url, expected in key.items():
        if expected:
            got = {k: stored[url][k] for k in expected}
            got["in_stock"] = bool(got["in_stock"])
            assert got == expected


def test_robots_disallowed_paths_never_requested(site, fast):
    crawl(site.base + "/catalogue/page-1.html", BOOKS, Store(":memory:"), fast)
    assert not any(e["path"].startswith(("/catalogue/hidden/", "/admin/")) for e in site.log)


def test_rerun_uses_304s_and_changes_nothing(site, fast):
    store = Store(":memory:")
    start = site.base + "/catalogue/page-1.html"
    crawl(start, BOOKS, store, fast)
    before = _stored(store)
    second = crawl(start, BOOKS, store, fast)
    assert second.new == 0 and second.changed == 0 and second.unchanged == len(before)
    assert second.outcomes.get("not_modified", 0) >= second.listing_pages + second.unchanged
    after = _stored(store)
    assert {u: r["content_hash"] for u, r in after.items()} == {
        u: r["content_hash"] for u, r in before.items()}


def test_changed_prices_are_detected_exactly(site, fast):
    store = Store(":memory:")
    start = site.base + "/catalogue/page-1.html"
    crawl(start, BOOKS, store, fast)
    old = {b.path: b.price_pence for b in site.books}
    site.set_version(2)
    crawl(start, BOOKS, store, fast)
    planted = {site.base + b.path for b in site.books
               if b.price_pence != old[b.path] and not b.broken and b.link != "hidden"}
    detected = {r[0] for r in store.conn.execute("SELECT url FROM changes WHERE field = 'price_pence'")}
    assert detected == planted


def test_pagination_loop_and_endless_trap_stop(site, fast):
    s = replace(fast, max_pages=50)
    loop = crawl(site.base + "/hostile/loop/page-1.html", BOOKS, Store(":memory:"), s)
    endless = crawl(site.base + "/hostile/endless/page-1.html", BOOKS, Store(":memory:"), s)
    assert loop.stop_reason == "loop" and loop.listing_pages == 3
    assert endless.stop_reason == "no_progress" and endless.listing_pages == 2


def test_max_pages_is_a_hard_cap(site, fast):
    stats = crawl(site.base + "/catalogue/page-1.html", BOOKS, Store(":memory:"), replace(fast, max_pages=7))
    assert stats.stop_reason == "max_pages"
    assert len([e for e in site.log if e["path"] != "/robots.txt"]) <= 7 + 2  # + retried attempts


def test_reports_written_and_consistent(site, fast, tmp_path):
    store = Store(":memory:")
    crawl(site.base + "/catalogue/page-1.html", BOOKS, store, fast)
    summary = build_summary(store.conn)
    paths = write_reports(summary, tmp_path)
    data = json.loads(paths[0].read_text())
    assert data["catalogue"]["books"] == len(_stored(store))
    assert str(data["catalogue"]["books"]) in paths[1].read_text()
    with paths[3].open(encoding="utf-8-sig") as fh:
        assert len(list(csv.DictReader(fh))) == data["catalogue"]["books"]


def test_percentile_nearest_rank():
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile([], 50) is None


def test_formula_cells_defused():
    assert defuse('=HYPERLINK("x")') == "'=HYPERLINK(\"x\")"
    assert defuse("-5 discount") == "'-5 discount"
    assert defuse("Normal title") == "Normal title"
    assert defuse(1234) == 1234


def test_html_report_escapes_scraped_text():
    summary = {
        "run": {"run_id": 1, "start_url": "http://x", "stop_reason": "done"},
        "crawl": {"requests": 1, "retries": 0},
        "catalogue": {"books": 1, "price_median_pence": 100, "in_stock_pct": 100.0,
                      "rating_counts": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1}},
        "changes": {"price_changes": []},
        "books": [{"url": "http://x/1", "title": "<script>alert(1)</script>", "category": "A",
                   "price_pence": 100, "rating": 5, "in_stock": 1, "stock_count": 1}],
    }
    assert "<script>alert(1)" not in render_html(summary)
    assert "&lt;script&gt;" in render_html(summary)


def test_cli_crawl_end_to_end(site, tmp_path, capsys):
    db = tmp_path / "s.db"
    code = main(["crawl", "--start", site.base + "/catalogue/page-1.html", "--db", str(db),
                 "--delay", "0", "--report-dir", str(tmp_path / "r"), "--quiet"])
    assert code == 0
    assert (tmp_path / "r" / "report.html").exists()
    assert "stop: done" in capsys.readouterr().out


def test_cli_refuses_rude_delay_on_public_sites(capsys):
    try:
        main(["crawl", "--start", "https://books.toscrape.com/", "--delay", "0.1"])
    except SystemExit as exc:
        assert "too fast" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_unchanged_304_pages_skip_parsing_unless_parser_changed(site, fast):
    from scraper.profiles.books import BooksProfile

    class Counting(BooksProfile):
        calls = 0

        def parse_item(self, *a):
            Counting.calls += 1
            return super().parse_item(*a)

    store = Store(":memory:")
    start = site.base + "/catalogue/page-1.html"
    crawl(start, Counting(), store, fast)
    first = Counting.calls
    Counting.calls = 0
    crawl(start, Counting(), store, fast)
    assert Counting.calls == first - len(_stored(store))  # only previously rejected pages re-parsed
    bumped = Counting()
    bumped.version = "books-test-new"
    Counting.calls = 0
    crawl(start, bumped, store, fast)
    assert Counting.calls == first  # new parser: everything re-parsed from the cache
