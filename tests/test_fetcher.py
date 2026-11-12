from dataclasses import replace
from datetime import UTC, datetime

from scraper.fetcher import Fetcher, charset_from_content_type, parse_retry_after
from scraper.storage import Store
from testsite.server import TestSite


def test_charset_from_header():
    assert charset_from_content_type("text/html; charset=UTF-8") == "utf-8"
    assert charset_from_content_type('text/html; charset="iso-8859-1"') == "iso-8859-1"
    assert charset_from_content_type("text/html") is None  # don't guess: let the parser sniff


def test_retry_after_seconds_and_date():
    assert parse_retry_after("120") == 120.0
    now = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Thu, 12 Nov 2026 12:00:30 GMT", now) == 30.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None


def test_ok_page_sends_our_user_agent(site, fast):
    f = Fetcher(fast, site.base)
    r = f.fetch(site.base + "/catalogue/page-1.html")
    assert r.outcome == "ok" and r.status == 200 and r.encoding is None
    assert b"product_pod" in r.body
    assert all(entry["ua"] == fast.user_agent for entry in site.log)


def test_robots_checked_before_any_request(site, fast):
    f = Fetcher(fast, site.base)
    r = f.fetch(site.base + "/admin/stats.html")
    assert r.outcome == "robots_blocked" and r.attempts == 0
    assert [e["path"] for e in site.log] == ["/robots.txt"]


def test_redirect_followed_and_final_url_recorded(fast):
    with TestSite(seed=7, n_books=400) as site:
        book = next(b for b in site.books if b.link == "redirect" and not b.fault)
        r = Fetcher(fast, site.base).fetch(site.base + book.listed_path)
        assert r.outcome == "ok" and r.redirects == 1
        assert r.final_url == site.base + book.path


def test_503_then_success_is_retried(fast):
    with TestSite(seed=7, n_books=400) as site:
        book = next(b for b in site.books if b.fault == "503" and b.link == "normal")
        r = Fetcher(fast, site.base).fetch(site.base + book.path)
        assert r.outcome == "ok" and r.attempts == 2 and r.retries == 1


def test_retry_after_is_honoured(fast):
    with TestSite(seed=5, n_books=400) as site:
        book = next(b for b in site.books if b.fault == "429" and b.link == "normal")
        Fetcher(fast, site.base).fetch(site.base + book.path)
        hits = [e["t"] for e in site.log if e["path"] == book.path]
        assert len(hits) == 2 and hits[1] - hits[0] >= 0.95  # server said Retry-After: 1


def test_conditional_get_returns_304_and_cached_body(site, fast):
    store = Store(":memory:")
    url = site.base + "/catalogue/page-1.html"
    first = Fetcher(fast, site.base, cache=store).fetch(url)
    second = Fetcher(fast, site.base, cache=store).fetch(url)
    assert first.outcome == "ok" and second.outcome == "not_modified"
    assert second.body == first.body and second.bytes_received == 0


def test_offsite_redirect_is_blocked(site, fast):
    r = Fetcher(fast, site.base).fetch(site.base + "/hostile/redirect/item.html")
    assert r.outcome == "out_of_scope"
    assert not any(e["path"].startswith("/internal/") for e in site.log)


def test_body_size_cap(site, fast):
    r = Fetcher(replace(fast, max_bytes=1_000_000), site.base).fetch(site.base + "/hostile/bomb/item.html")
    assert r.outcome == "too_large"


def test_total_time_cap_stops_a_dripping_server(site, fast):
    s = replace(fast, timeout_s=0.6, max_retries=0)
    r = Fetcher(s, site.base).fetch(site.base + "/hostile/drip/item.html")
    assert r.outcome == "network_error" and r.elapsed_ms < 1500


def test_non_html_refused(site, fast):
    r = Fetcher(fast, site.base).fetch(site.base + "/hostile/notHtml/item.html")
    assert r.outcome == "not_html"


def test_retries_are_capped(site, fast):
    r = Fetcher(replace(fast, max_retries=2), site.base).fetch(site.base + "/hostile/storm/item.html")
    assert r.outcome == "http_error" and r.status == 503 and r.attempts == 3


def test_unreachable_host_is_a_network_error(fast):
    s = replace(fast, max_retries=0, respect_robots=False, timeout_s=0.5)
    r = Fetcher(s, "http://127.0.0.1:9").fetch("http://127.0.0.1:9/")
    assert r.outcome == "network_error"
