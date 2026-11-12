# Design: web-scraper

**One page. What it must do, the decisions that shape it, and the alternatives that lost.**

## Goal and constraints

Turn a public catalogue site into structured rows and a change report, **without being a bad guest**. In priority order:

1. **Never break the site's rules.** Obey robots.txt to the standard (RFC 9309), keep at least the configured gap between requests, honour `Crawl-delay` and `Retry-After`. A scraper that's 100% accurate but ignores robots.txt has failed.
2. **Never store wrong data quietly.** A page we can't read is rejected with a reason. It's never half-stored.
3. **Survive hostile pages** (traps, size bombs, slow servers, injection payloads) without crashing or hanging.
4. **Cheap reruns.** The second visit should cost almost nothing when nothing changed.
5. **Learnable.** Three dependencies, small modules, one site-specific file.

Non-goals for v0.1: JavaScript rendering, many sites at once, distributed crawling.

## Decisions

| # | Decision | Alternatives considered | Why they lost |
|---|---|---|---|
| 1 | **`requests` + BeautifulSoup (lxml backend)** | **Scrapy**: a full framework with scheduling, throttling and pipelines. **httpx + selectolax**: faster. **Playwright**: a real browser. | Scrapy hides exactly the HTTP and parsing concepts this project exists to teach, and its middleware stack is a lot to explain in an interview. selectolax is faster, but CSS selectors in BeautifulSoup are the lingua franca, and parsing isn't the bottleneck at 1 request/s anyway. Playwright is 100s of MB for sites that don't need JavaScript. |
| 2 | **Own RFC 9309 robots matcher** | `urllib.robotparser` (stdlib); `protego` (Scrapy's parser). | The stdlib gives different answers on Python 3.11/3.12 vs 3.13, and some of them are unsafe (postmortem). `protego` is good but is one more dependency for ~150 lines of logic that's worth understanding. The gold set pins the behaviour either way. |
| 3 | **Single-threaded, per-host rate limiter measured from the last request** | Thread pool / asyncio with a semaphore; a token bucket. | Politeness caps us at about 1 request/s per host, so concurrency buys nothing for one site and makes the "gap ≥ delay" guarantee much harder to prove. A token bucket allows bursts, which is exactly what a small server doesn't want. |
| 4 | **Follow redirects by hand** (`allow_redirects=False`) | Let `requests` follow them. | Automatic redirects skip our scope and robots checks on every hop. One `302` to `http://169.254.169.254/` and we've fetched a cloud metadata server (an SSRF). The attack eval proves this: switch the scope check off and the redirect attack lands. |
| 5 | **Bounded reads with a total deadline** (`read1` loop, `max_bytes`, total time) | `requests`' `timeout=` alone; `response.content`. | `timeout=` is per socket read, so a server sending 1 byte every 0.25 s never trips it. `response.content` reads everything into memory, however big. Both were demonstrated by the attack eval. |
| 6 | **Bytes to the parser; charset only from the header if it's actually there** | `response.text` | `requests` assumes ISO-8859-1 for `text/html` without a charset, which produces `Â£`. BeautifulSoup sniffs `<meta charset>` and BOMs from bytes. |
| 7 | **SQLite, typed `books` table, `changes` history, `fetch_log`** | CSV/JSON files; a generic `items(url, json)` table; Postgres. | Files can't do "has this changed?" without reloading everything. A JSON blob table is flexible but loses typed SQL for reports (`AVG(price_pence)`). Postgres is overkill for one writer. The profile owns the schema, so a new site gets its own typed table. |
| 8 | **Change detection: conditional GET + content hash + skip-parse on 304** | Always re-download and diff; hash the raw HTML. | Re-downloading is impolite and slow. Hashing raw HTML reports a "change" whenever a footer or CSRF token changes, so we hash the *extracted fields*. Skipping the parse on a 304 is safe only if the parser is unchanged, so rows record `parser_version`. |
| 9 | **Site profile = 2 methods** (`parse_listing`, `parse_item`) | One generic scraper driven by config; ML/LLM extraction. | Config-driven selectors are great for simple sites (Next steps) but can't express "ignore the struck-out price". LLM extraction is non-deterministic, costs per page, and can't be tested exactly. |
| 10 | **Local test site with an answer key + hostile routes** | Test against the live sandbox; recorded fixtures (VCR). | Live tests are flaky, load someone else's server and can't produce planted errors with known answers. Recorded fixtures can't do timing (drip, Retry-After) or show the server's view of politeness. |

## Defences: what and where

| Threat | Defence | Where | Proven by |
|---|---|---|---|
| Fetching disallowed pages | RFC 9309 matcher, checked before every hop | `robots.py`, `fetcher.fetch` | gold set; attack `robots`; 0 disallowed in 5,600+ logged requests |
| Overloading the server | per-host gap, `Crawl-delay`, `Retry-After`, capped retries with jittered backoff | `ratelimit.py`, `fetcher._get_with_retries` | politeness eval (client + server clocks); attacks `retryafter`, `storm` |
| Infinite crawl | visited set, no-progress stop, hard `max_pages` | `crawler.py` | attacks `loop`, `endless` |
| SSRF / scheme tricks | http(s) + same host only, every redirect hop | `urls.in_scope` | attack `redirect` |
| Memory / time exhaustion | `max_bytes` (header + streamed), per-read timeout, total deadline | `fetcher._get_bounded` | attacks `bomb`, `slow`, `drip` |
| Content-type confusion | parse only `text/html` | `fetcher` | attack `notHtml` |
| Injection into outputs | parameterised SQL; HTML-escape; CSV formula guard | `storage.py`, `report.py` | attacks `sqli`, `xss`, `formula` |

## Risks I'm accepting

- The test site and the parser share my assumptions; the gold set is the partial answer and real-site runs are the full one.
- One profile. The abstraction is only proven once there are two.
- Being polite makes it slow: about 18 minutes for 1,000 books. Rather than adding parallelism, the fix is sitemaps with `<lastmod>`, which skip unchanged pages altogether.
