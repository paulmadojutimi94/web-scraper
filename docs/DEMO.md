# Demo: 3 minutes, 11 scenes

The video ([GIF](demo/web-scraper-demo.gif), [MP4](demo/web-scraper-demo.mp4)) is built by `make video` from real output: `examples/demo_output.txt` (written by `make demo`) and `evals/results/*.json` (written by `make eval`). Rebuild it after either changes. Below is the narration to read over it, or to use as a live-demo script.

| # | Scene | Time | Say |
|---|---|---|---|
| 1 | Title | 0:00-0:10 | "This is a web scraper that turns a public catalogue into a database and a change report, built to be a good guest on someone else's server." |
| 2 | The problem | 0:10-0:28 | "The scraping code itself fits on a napkin: fetch, find the price, follow 'next'. What's hard is being polite and staying safe. There's a sign on the door, robots.txt. There's one till, so you queue. If the server says come back later, you do. And some pages are hostile on purpose." |
| 3 | HTTP, one request | 0:28-0:48 | "Before anything is sent, it reads robots.txt. The admin page is blocked with zero attempts: no request ever leaves. The catalogue page comes back 200 in a few milliseconds. Note the charset line: the server didn't say, so the parser reads the page's own meta tag. That's what avoids the classic 'Â£' bug." |
| 4 | Run 1 | 0:48-1:04 | "Full crawl: 50 listing pages, 990 product pages. 982 books stored. 8 pages were planted broken, and they're rejected with a reason rather than half-stored. 10 links point into a folder robots.txt disallows, and they were never requested." |
| 5 | The report | 1:04-1:22 | "Every run writes Markdown, HTML, CSV and JSON from one summary, so they can't disagree. Anything scraped is HTML-escaped, and CSV cells are defused so a 'book title' can't become an Excel formula." |
| 6 | Run 2 | 1:22-1:37 | "Same site again. Every page answers 304 Not Modified. We sent the ETag, the server said 'same as yours'. 61 bytes of body instead of 2.1 MB, and since the bytes are identical we don't even re-parse. 2.3 seconds instead of 12.6." |
| 7 | Run 3 | 1:37-1:55 | "Now the shop changes 5% of its prices. The scraper finds every one, and nothing else, and keeps a field-level history: old price, new price, which run." |
| 8 | What the 100% eval missed | 1:55-2:20 | "My own test site said 100%. But I'd written the site and the scraper, so they shared my blind spots. So before the first run I committed 44 hand-written real-world cases. First run: 34. The worst were robots.txt: chasing them showed Python's built-in parser gives different, unsafe answers on 3.11 and 3.12. It would have crawled pages the site disallowed. So I wrote a 150-line matcher to the standard, 18 out of 18 on every version, and CI runs all three." |
| 9 | 14 hostile pages | 2:20-2:42 | "Fourteen attack pages: a loop, an endless 'next', a redirect to an internal host, a 20 MB page, a server that drips one byte every quarter-second, script tags and Excel formulas as titles. None get through. Zero on its own proves nothing, so each defence has an off switch: turn it off and its attack lands. Every one. That's what shows the tests are real." |
| 10 | Hard numbers | 2:42-2:58 | "Accuracy, politeness from the server's own log, change detection, latency, cost: all from `make eval`. The honest caveat is the 100% row: my site, my scraper. The gold set and a real-site run are what count." |
| 11 | Next | 2:58-3:10 | "Next: run it against the real sandbox from a normal machine and freeze a second gold set from whatever it gets wrong. The learning guide and the line-by-line cheatsheet are in docs." |

## Live-demo version (no video)

```bash
make serve &                         # the practice site
export PYTHONPATH=src
python3 -m scraper robots http://127.0.0.1:8000/catalogue/page-1.html
python3 -m scraper fetch http://127.0.0.1:8000/admin/stats.html        # blocked, 0 attempts
python3 -m scraper crawl --start http://127.0.0.1:8000/catalogue/page-1.html --delay 0 --db demo.db
python3 -m scraper crawl --start http://127.0.0.1:8000/catalogue/page-1.html --delay 0 --db demo.db  # 304s
python3 -m scraper crawl --start http://127.0.0.1:8000/hostile/endless/page-1.html --delay 0 --db t.db  # stops: no_progress
open reports/report.html
```

Questions to expect afterwards are in [CHEATSHEET.md](CHEATSHEET.md#30-second-answers).
