# Learn HTTP, BeautifulSoup and parsing through this scraper

Four lessons, each built on code in this repo, each ending with exercises you can run against the local test site. No internet needed: start the practice site in one terminal and keep it running.

```bash
make serve          # http://127.0.0.1:8000/catalogue/page-1.html
export PYTHONPATH=src
```

---

## Lesson 1: HTTP, the conversation at the door

Every web page is the answer to a short, formal conversation. Your program knocks (a **request**), the server answers (a **response**). Both have the same shape: a first line, some **headers** (labelled facts, like the labels on a parcel), then optionally a **body** (the parcel itself).

```text
GET /catalogue/page-1.html HTTP/1.1          <- method, path, version
Host: 127.0.0.1:8000                         <- which site (one server can host many)
User-Agent: web-scraper/0.1 (+https://...)   <- who's knocking
If-None-Match: "3f2a9c1e7d0b4a55"            <- "I have version 3f2a..., anything newer?"

HTTP/1.0 304 Not Modified                    <- status code + reason
ETag: "3f2a9c1e7d0b4a55"
                                             <- no body: "what you have is current"
```

See it yourself:

```bash
python3 -m scraper fetch http://127.0.0.1:8000/catalogue/page-1.html --show 400
curl -i http://127.0.0.1:8000/catalogue/page-1.html | head -12      # the raw headers
```

### Status codes: the first digit is the whole story

| Code | Means | Real-world version | What this scraper does |
|---|---|---|---|
| **2xx** | Success | "Here you go" | parse it |
| **301 / 302** | Moved | "We've moved to number 12" | follow it *by hand*, re-checking the rules (`fetcher.fetch`) |
| **304** | Not modified | "Same as the copy you already have" | use the cached copy (`_get_with_retries`) |
| **404** | Not found | "No such shop" | log it, move on, don't retry |
| **429** | Too many requests | "You're in here every 5 minutes, come back in an hour" | wait the `Retry-After`, then try again |
| **5xx** | Server error | "Sorry, the till's broken" | back off and retry, at most 3 times |

**Retry or not?** Ask "could the answer be different in a minute?" A 503 (overloaded) could; a 404 won't. That's `RETRY_STATUSES` in `fetcher.py`.

### Headers that matter for scraping

- **`User-Agent`**: who you are. Be honest and give a URL; anonymous bots get blocked.
- **`Content-Type: text/html; charset=UTF-8`**: what the body is and how its bytes become letters.
- **`Location`**: where a redirect points.
- **`ETag` / `Last-Modified`** → send back as **`If-None-Match` / `If-Modified-Since`**: the "has it changed?" question.
- **`Retry-After`**: how long to stay away, in seconds or as a date.
- **`Content-Length`**: how big the body says it is. Don't trust it blindly (a hostile server may leave it out: `/hostile/bomb/`).

### Bytes vs text: the `Â£` bug

A body is **bytes**. `£` in UTF-8 is two bytes, `C2 A3`. If you decode those two bytes as ISO-8859-1 (one byte = one letter) you get two letters: `Â£`. `requests` does exactly that when a server says `text/html` without a charset. The test site does this on purpose:

```python
import requests
r = requests.get("http://127.0.0.1:8000/catalogue/page-1.html")
print(r.headers["Content-Type"], r.encoding)     # text/html ISO-8859-1  <- requests guessed
print("Â£" in r.text, "£" in r.content.decode("utf-8"))   # True True
```

The fix in this repo: hand the **bytes** to BeautifulSoup, which reads the page's own `<meta charset="UTF-8">` (`charset_from_content_type` + `make_soup`).

### Being polite (the bonus)

- **robots.txt** is the sign on the door. `python3 -m scraper robots http://127.0.0.1:8000/admin/x` tells you what it says. The rules: the longest matching rule wins, and Allow wins a tie. `robots.py` implements the standard (RFC 9309) because Python's built-in parser didn't on every version (see the postmortem).
- **Rate limit:** one request per second per host by default (`ratelimit.py`). The CLI refuses less than 0.5 s for public sites.
- **Backoff with jitter:** after a failure wait 0.5 s, then 1 s, then 2 s, each randomly stretched or squeezed. Exponential so you don't hammer a struggling server; random so a thousand clients don't all come back at the same instant.
- **Timeouts:** `requests.get(url)` with no timeout can wait *forever*. Even `timeout=10` only limits each read, so a server that drips one byte at a time never trips it. `_get_bounded` adds a total deadline.

### Exercises

1. Fetch `/admin/stats.html` with the CLI. Why does it say `robots_blocked` with `attempts 0`? Find the line that decides.
2. With `curl -i -H 'If-None-Match: "x"'` and then with the real ETag, compare the two responses. Which one has a body?
3. Find a book with `fault == "429"` (`from testsite.generator import generate`), fetch it twice with the CLI, and read the server's answer the first time.
4. Change `min_delay_s` to `0` in a script and crawl the test site with `time`. Then try `--delay 0` against `https://books.toscrape.com` with the CLI. What happens, and why is that line there?

---

## Lesson 2: HTML is a tree

HTML looks like text, but a browser (and BeautifulSoup) turns it into a **tree**, like a family tree or folders inside folders:

```text
article.product_pod
├── div.image_container
│   └── a[href="a-light-in-the-attic_1000/index.html"]
│       └── img
├── p.star-rating.Three
├── h3
│   └── a[href=...][title="A Light in the Attic"]  "A Light in the ..."
└── div.product_price
    ├── p.price_color  "£51.77"
    └── p.instock.availability  "In stock"
```

Every scraping question becomes "how do I point at that node?". The two answers are **CSS selectors** and walking the tree.

### CSS selectors: an address for nodes

| Selector | Means | Used for |
|---|---|---|
| `p` | every `<p>` | |
| `.price_color` | any element with class `price_color` | |
| `p.price_color` | a `<p>` with that class | |
| `article.product_pod h3 a` | an `<a>` *somewhere inside* an `<h3>` inside a product card (space = descendant) | item links |
| `a[href]` | an `<a>` that *has* an `href` | skip anchors without links |
| `ul.pager li.next a` | the "next" link in the pager | pagination |
| `a[rel~="next"]` | `rel` contains the word `next` | the standard pagination hint |
| `#product_description ~ p` | a `<p>` that's a later *sibling* of the element with id `product_description` | the description |

```python
from bs4 import BeautifulSoup
import requests
html = requests.get("http://127.0.0.1:8000/catalogue/page-1.html").content   # bytes!
soup = BeautifulSoup(html, "lxml")

links = soup.select("article.product_pod h3 a[href]")     # list of Tags
first = links[0]
first["href"]          # 'the-quiet-garden-vol-3_1/index.html'  (relative!)
first["title"]         # the full title
first.get_text()       # the visible, possibly truncated text
soup.select_one("ul.pager li.next a")["href"]   # 'page-2.html'
```

`select` returns a list; `select_one` returns the first match or `None`. **Always handle `None`**: a missing element is how most scrapers crash on page 400 of 1,000.

### Walking the tree

```python
price = soup.select_one("p.price_color")
price.parent                 # the div.product_price
price.find_next_sibling("p") # the availability paragraph
row.find("th")               # first <th> inside row, or None
tag.get("class")             # ['star-rating', 'Three']  (class is a list!)
```

### Relative links

`href="page-2.html"` means "next to the current page". `urljoin` resolves it, the way `cd` does in a terminal:

```python
from urllib.parse import urljoin
urljoin("http://x/catalogue/page-1.html", "page-2.html")       # http://x/catalogue/page-2.html
urljoin("http://x/catalogue/a_1/index.html", "../../index.html")  # http://x/index.html
```

Unless the page has `<base href="...">`, which changes what "here" means (gold case `l01`; `base_url()` in `books.py`).

### Exercises

5. Write a selector for the star rating of every book on page 1 and turn the class names into numbers.
6. Print every book on page 1 whose listing title ends in `...`. Where does the full title live?
7. Why does `parse_item` look for the price inside `div.product_main` instead of anywhere on the page? (Hint: what would a "you might also like" carousel do?)
8. Save page 1 to a file, delete the `<ul class="pager">`, add `<a rel="next" href="page-2.html">`, and check `BooksProfile().parse_listing` still finds the next page.

---

## Lesson 3: Parsing text into values

The tree gives you **strings**. Your database wants **types**. This step is where silent errors are born, so every function in `fields.py` returns either a correct value or `None`, never a guess.

### Prices: never use float for money

```python
>>> float("1.15") * 100
114.99999999999999
>>> int(float("1.15") * 100)
114                          # a penny vanished
>>> from decimal import Decimal
>>> int(Decimal("1.15") * 100)
115
```

Floats store numbers in binary, and 1.15 has no exact binary form, the way 1/3 has no exact decimal form. `parse_price_pence` uses `Decimal` and stores whole pence as an integer.

### Regular expressions, read aloud

```python
_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
```

"*Either* 1-3 digits followed by one or more groups of comma-plus-3-digits (`1,234,567`), *or* just digits (`1234`). Then, optionally, a dot and 1-2 digits.". `(?:...)` groups without capturing; `?` means optional. `search` finds it anywhere, so `£`, `Â£` or `GBP ` in front doesn't matter.

### Whitespace and Unicode

Real pages are full of `\n    In stock\n\n`. `" ".join(text.split())` collapses any run of whitespace, including non-breaking spaces (` `), into a single space. `unicodedata.normalize("NFC", ...)` makes `é` (one character) and `e` + `́` (two characters, which look identical) the same string.

### Validate, then store

`parse_item` checks the required fields (title, UPC, price) and returns **reasons** instead of an item if any are missing. The page is logged in `rejects`. Half a record in the database is worse than none: a report that averages prices will happily average in a zero.

### Exercises

9. Add `"£1.234,56"` (European style) to `test_price` in `tests/test_fields_urls.py`. What does the parser return? Is that a bug or a correct refusal for a UK site? Write down your decision.
10. `parse_availability("Pre-order")` returns `(None, None)`. Why is that better than `(False, 0)`?
11. Add a gold case of your own to a *copy* of `evals/gold/cases.py` (the real one is frozen) for a price written `"£12.99 (was £15.99)"`. Predict the result, then run it.

---

## Lesson 4: Pagination, storage and reports

### Pagination is a loop with three exits

```text
url = page 1
while url:
    if url in seen:                      -> stop "loop"
    page = fetch(url); items = parse(page)
    if no new items on this page:        -> stop "no_progress"
    if requests >= max_pages:            -> stop "max_pages"
    url = next link (or None)            -> stop "done"
```

Each exit exists because of a real trap: a "next" link that points back (`/hostile/loop/`), a "next" that goes on forever repeating the same products (`/hostile/endless/`), and anything nobody imagined (the cap). Run them:

```bash
python3 -m scraper crawl --start http://127.0.0.1:8000/hostile/loop/page-1.html --delay 0 --db t.db
python3 -m scraper crawl --start http://127.0.0.1:8000/hostile/endless/page-1.html --delay 0 --db t.db
```

### Storage: "has anything changed?"

The `books` table has one row per URL (`PRIMARY KEY`). Each row stores a **content hash**, a fingerprint of the extracted fields. On the next visit: same fingerprint means touch `last_seen_run` and move on; a different one means write a `changes` row per field that moved. That's how the report can say "£56.44 → £64.78" without storing every version of every page.

```bash
python3 -m scraper serve-testsite --version 2 --port 8001    # the same shop, a week later
sqlite3 scraper.db "SELECT title, old_value, new_value FROM changes JOIN books USING(url) LIMIT 5"
```

### Reports: four views of one dict

`build_summary` runs the SQL once; `report.md`, `report.html`, `books.csv` and `summary.json` all render that same dict, so they can't disagree. Two safety rules apply to anything scraped that lands in a file someone opens:

- **HTML:** escape it. A book titled `<script>...` must show as text.
- **CSV:** a cell starting with `=`, `+`, `-` or `@` is a *formula* to Excel. `defuse()` prefixes `'`.

### Exercises

12. Crawl the test site twice. In `scraper.db`, compare the two runs with `SELECT outcome, COUNT(*) FROM fetch_log GROUP BY run_id, outcome`. Where did all the 200s go?
13. Restart the site with `--version 2` and crawl again. Check the number of price changes in `report.md` against `SELECT COUNT(*) FROM changes WHERE field='price_pence'`.
14. Open `examples/books.csv` in a spreadsheet. Then run `attack_eval.py` with `guard_formulas=False` for the `formula` attack only, open that CSV, and see what the title turned into.
15. **Write a second profile.** Copy `profiles/books.py` to a new file for a different practice site (e.g. quotes.toscrape.com: quote text, author, tags), register it in `get_profile`, and crawl it with `--max-pages 5`. What did you have to change outside the profile? (Ideally nothing.)
