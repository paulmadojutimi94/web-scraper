# Postmortem: web-scraper v0.1

Blameless, in the usual format: what happened, how it was found, why, what changed, and what stops it happening again. Five incidents, most serious first. All happened during development. None reached a real website, because the build sandbox couldn't reach the internet and every crawl ran against the local test site.

---

## 1. The scraper's politeness depended on the Python version (severity: high)

**What happened.** The accuracy eval reported 100% on ~5,000 books and **0** requests to robots-disallowed pages. The first run of the hand-written gold set reported **34 / 44**. Two failures were robots.txt cases:

```text
FAIL r14_utf8_bom: expected allowed=False, got True (UNSAFE: fetches a disallowed page)
FAIL c02_decimal: expected crawl-delay 2.5, got None
```

**How it was found.** The gold set (`evals/gold/cases.py`) was written from RFC 9309's rules and committed in `3b1cf78` *before* the scraper had run on any of it, so the expectations couldn't drift to match the code. While chasing the two robots failures, I ran the same 18 cases through Python's `urllib.robotparser` on every interpreter in the sandbox:

| Python | stdlib result | Unsafe answers |
|---|---|---|
| 3.11.18 | 12 / 18 | 4: longest match, `*.pdf$`, `*?sort=`, BOM |
| 3.12.3 | 12 / 18 | 4: same |
| 3.13.18 | 16 / 18 | 1: BOM |

(`evals/robots_stdlib_compare.py` reproduces this; results in `evals/results/robots_stdlib.json`.)

**Root cause.** I assumed "it's in the standard library, so it implements the standard". `urllib.robotparser` is older than RFC 9309 (2022). Before recent versions it used the **first** matching rule instead of the **longest**, and treated `*` and `$` as literal characters. Even the newest version doesn't strip a UTF-8 byte-order mark (which Windows editors add), so the first line reads `﻿User-agent` and the whole group is ignored. It also only accepts whole-number `Crawl-delay` values.

**Why the 100% eval missed it.** The test site's robots.txt has two plain prefix rules (`Disallow: /admin/`, `Disallow: /catalogue/hidden/`), which every version gets right. The eval measured agreement between my site and my scraper, and both had the same blind spot.

**Impact (had it shipped).** On Python 3.11/3.12, a site writing `Allow: /catalogue/` then `Disallow: /catalogue/private/` would have had its private folder crawled. `Disallow: /*?sort=` (common, to keep bots off endless sort orders) would have been ignored, and that's exactly how crawlers get trapped and IP-banned. No error, no log line: the requests would simply have happened.

**Fix.** `robots.py` now has its own ~150-line parser and matcher: longest match wins, Allow wins ties, `*` and `$`, case-insensitive user-agent groups, percent-encoding normalised, BOM stripped, decimal `Crawl-delay`. 18 / 18 on 3.11, 3.12 and 3.13. Each rule is pinned by a unit test.

**Guard.** CI runs the full test suite on Python 3.11, 3.12 and 3.13, and runs `robots_stdlib_compare.py` on each so the stdlib's behaviour is on record. The gold set is never edited to make a case pass.

---

## 2. A 1-second timeout that waited 6 seconds (severity: high)

**What happened.** `test_total_time_cap_stops_a_dripping_server` failed: against a server sending one byte every 0.25 s, a fetch with `timeout_s=0.6` took **6,008 ms**.

**How it was found.** The test existed because the design said "per-read timeouts don't stop a slow drip", so the fetcher had a total-time check inside its read loop. The test showed the check never ran.

**Root cause.** The loop was `for chunk in resp.iter_content(65536)`. `iter_content` asks urllib3 for 65,536 bytes, and urllib3 keeps reading until it has them all or the connection closes. Each byte arrived well inside the per-read timeout, so the call returned once, after 6 s, with all 24 bytes, and only then did the deadline check run.

**Fix.** Read with `resp.raw.read1(65536)`, which returns as soon as *any* bytes arrive, so the deadline is checked after every trickle. The test now finishes in under 1 s, and the `drip` attack fails unless `guard_total_time` is switched off.

**Lesson.** "I wrote a timeout check" and "the timeout fires" are different claims. Only a hostile test server can tell them apart.

---

## 3. The rate limiter ignored the Crawl-delay it had just read (severity: medium)

**What happened.** The politeness eval, which reads the *server's* request log, found **2** gaps of 0.10 s on a site whose robots.txt said `Crawl-delay: 0.3`.

**How it was found.** Re-running that case and listing every gap under 0.3 s showed the pattern: `/robots.txt -> /catalogue/page-1.html`, 0.100 s apart, the first request after robots.txt.

**Root cause.** The limiter booked the *next* slot in advance: `next_ok = now + delay`, using the delay known at that moment. The robots.txt request itself went out with the default 0.1 s, so the next slot was booked 0.1 s ahead. Only then did we read `Crawl-delay: 0.3`, too late for the very next request.

**Fix.** The limiter now remembers when it *last* contacted each host and computes `ready = last + delay` with the delay known *now* (plus any `Retry-After` pause). Regression test: `test_delay_learned_later_still_applies_to_the_next_request`.

**Follow-up: two more milliseconds.** After the fix, the client-side check still found 1 gap of 0.1971 s against 0.2 s. Two causes, both fixed: the limiter recorded "last contact" when it *released* a request rather than when the request was *sent*, so anything delaying the send shortened the next gap (now `mark_sent()` runs immediately before `session.get`); and the test server ran in the same Python process, so its threads competed with the scraper for the GIL (the eval now runs it in a separate process). A later full run still saw one gap 2.5 ms short in 584 that didn't reproduce, which is a pause between `mark_sent()` and the timestamp. That's documented as a known limit rather than hidden by a looser tolerance.

**Guard.** Politeness is measured at both ends: client timestamps as each request leaves (0.5 ms tolerance) and the server's log from a separate process (20 ms tolerance for thread-scheduling jitter).

---

## 4. The rerun was no faster than the first crawl (severity: low, performance)

**What happened.** After adding conditional GETs, a rerun of an unchanged 1,000-book site still took about as long as the first crawl, even though 99% of responses were `304 Not Modified`.

**How it was found.** `cProfile` on a rerun: 2.36 s of 3.58 s was in `parse_item`. The 304 had saved the download, but the code then parsed the cached copy again.

**Fix.** On a 304 for a book we already hold, *parsed by the same parser version*, just mark it seen. `books.parser_version` makes this safe: change the profile and bump `BooksProfile.version`, and every cached page is re-parsed once. A 300-book rerun went from 3.6 s to 1.7 s; the 1,000-book demo rerun takes 2.3 s.

---

## 5. Two bugs in the evals themselves (severity: low, but they would have misled)

**a) "Stock changes found: 166 / 171."** It looked like 5 misses. All 5 were stock counts that changed behind a page saying only "In stock" (no number). Nothing on the page changed, so there was nothing to find. The eval compared against the generator's hidden state instead of what a reader could see. Fixed to count visible changes only: 166 / 166.

**b) Rerun timing included the planted faults again.** `site.reset_log()` also re-armed the "fail the first request" faults, so the "nothing changed" rerun paid ~5 s of 503/429 retries a second time. Fixed with `reset_log(hits=False)`.

**Lesson.** Before calling an eval result a scraper bug, check that the eval is measuring what a perfect scraper could actually do.

---

## Also fixed from the gold set's first run

| Case | Symptom | Fix |
|---|---|---|
| `p09` sale price | `<del>£20.00</del> £15.00` stored as £20.00 | ignore text inside `del`/`s`/`strike` |
| `p13` "Only 3 left" | stock count `NULL` | count pattern accepts `N left` |
| `p18`, `p19` `UPC:` / `upc` | page rejected | table labels normalised (case, trailing colon) |
| `l01` `<base href>` | item URLs resolved against the wrong folder | resolve against `<base href>` when present |
| `l02` `rel="next"` | pagination stopped after page 1 | fall back to `a[rel~=next]`, `link[rel~=next]` |
| `l03` whitespace in `href` | URL ending in spaces | strip whitespace as browsers do |
| `l05` `javascript:` link | listed as an item URL | keep only http(s) item links |
| `test_normalize` | `/a/../b/` not collapsed without a base URL | always resolve dot-segments |
