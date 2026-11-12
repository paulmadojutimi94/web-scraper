from scraper.ratelimit import HostRateLimiter
from scraper.robots import RobotsCache, parse_robots

UA = "web-scraper/0.1"


def test_rules_parsed():
    p = parse_robots(200, "User-agent: *\nDisallow: /admin/\nCrawl-delay: 2\n")
    assert p.allowed("http://x.test/catalogue/a.html", UA)
    assert not p.allowed("http://x.test/admin/stats.html", UA)
    assert p.crawl_delay(UA) == 2.0


def test_status_codes_follow_rfc9309():
    assert parse_robots(404, "").allowed("http://x.test/anything", UA)  # no file: no rules
    assert parse_robots(403, "").allowed("http://x.test/anything", UA)  # RFC: 4xx = allow
    assert not parse_robots(503, "").allowed("http://x.test/anything", UA)  # server error: stay out
    assert not parse_robots(0, "").allowed("http://x.test/anything", UA)  # unreachable: stay out


def test_specific_user_agent_group_wins():
    text = "User-agent: web-scraper\nDisallow: /\n\nUser-agent: *\nDisallow:\n"
    p = parse_robots(200, text)
    assert not p.allowed("http://x.test/page", "web-scraper/0.1")
    assert p.allowed("http://x.test/page", "SomeOtherBot")


def test_robots_fetched_once_per_host():
    calls = []

    def fetch_text(url):
        calls.append(url)
        return 200, "User-agent: *\nDisallow: /private/\n"

    cache = RobotsCache(fetch_text, UA)
    assert cache.allowed("http://a.test/x")
    assert not cache.allowed("http://a.test/private/y")
    assert cache.allowed("http://b.test/private/y") is False
    assert calls == ["http://a.test/robots.txt", "http://b.test/robots.txt"]


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


def test_rate_limiter_spaces_requests_per_host():
    clock = FakeClock()
    rl = HostRateLimiter(clock=clock, sleep=clock.sleep)
    rl.wait("a", 1.0)  # first request: no wait
    rl.wait("a", 1.0)  # second: wait the full second
    rl.wait("b", 1.0)  # a different host: no wait
    clock.now += 5
    rl.wait("a", 1.0)  # plenty of time has passed: no wait
    assert clock.sleeps == [1.0]


def test_pause_pushes_the_next_slot_back():
    clock = FakeClock()
    rl = HostRateLimiter(clock=clock, sleep=clock.sleep)
    rl.wait("a", 0.5)
    rl.pause("a", 3.0)  # server said Retry-After: 3
    rl.wait("a", 0.5)
    assert clock.sleeps == [3.0]


# --- regressions found by the gold set (RFC 9309) ------------------------------------------
def test_longest_match_wins_not_first_match():
    p = parse_robots(200, "User-agent: *\nAllow: /catalogue/\nDisallow: /catalogue/private/\n")
    assert not p.allowed("http://x.test/catalogue/private/a.html", UA)
    assert p.allowed("http://x.test/catalogue/page-1.html", UA)
    p = parse_robots(200, "User-agent: *\nDisallow: /\nAllow: /catalogue/\n")
    assert p.allowed("http://x.test/catalogue/page-1.html", UA)


def test_allow_wins_a_tie():
    p = parse_robots(200, "User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert p.allowed("http://x.test/page", UA)


def test_wildcards_and_end_anchor():
    p = parse_robots(200, "User-agent: *\nDisallow: /*.pdf$\nDisallow: /*?sort=\n")
    assert not p.allowed("http://x.test/a/b.pdf", UA)
    assert p.allowed("http://x.test/a/b.pdf?dl=1", UA)
    assert not p.allowed("http://x.test/list?sort=price", UA)
    assert p.allowed("http://x.test/list?page=2", UA)


def test_bom_does_not_hide_the_first_group():
    assert not parse_robots(200, "﻿User-agent: *\nDisallow: /\n").allowed("http://x.test/a", UA)


def test_decimal_crawl_delay_and_specific_group():
    assert parse_robots(200, "User-agent: *\nCrawl-delay: 2.5\n").crawl_delay(UA) == 2.5
    text = "User-agent: web-scraper\nCrawl-delay: 3\n\nUser-agent: *\nCrawl-delay: 1\n"
    assert parse_robots(200, text).crawl_delay(UA) == 3.0
    assert parse_robots(200, "User-agent: *\nCrawl-delay: soon\n").crawl_delay(UA) is None


def test_percent_encoding_is_normalised():
    p = parse_robots(200, "User-agent: *\nDisallow: /%7Ejoe/\n")
    assert not p.allowed("http://x.test/~joe/index.html", UA)


def test_robots_txt_itself_is_always_allowed():
    assert parse_robots(200, "User-agent: *\nDisallow: /\n").allowed("http://x.test/robots.txt", UA)
