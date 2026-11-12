# CLAUDE.md: guide for AI agents working in this repo

A polite web scraper (fetch → extract → paginate → store → report) for books.toscrape.com-style catalogues, plus a local test site and evals. Python 3.11+, deps: `requests`, `beautifulsoup4`, `lxml`.

## Commands

```bash
make test        # 78 tests, ~15 s. Must pass before any commit.
make lint        # ruff
make eval        # ~4 min; rewrites evals/results/*.json and the README results table
make eval-check  # what CI runs: README table == results files
make demo        # rewrites examples/
```

Always `export PYTHONPATH=src` (the Makefile does).

## Map

| Module | Owns | Don't put here |
|---|---|---|
| `src/scraper/config.py` | every setting (frozen dataclass) | logic |
| `src/scraper/urls.py` | normalisation, scope | HTTP |
| `src/scraper/robots.py` | RFC 9309 parsing + matching | HTTP (it receives a `fetch_text` function) |
| `src/scraper/ratelimit.py` | per-host spacing, pauses | anything else |
| `src/scraper/fetcher.py` | one polite GET → `FetchResult` | parsing, database |
| `src/scraper/fields.py` | text → typed values | HTML |
| `src/scraper/profiles/books.py` | the only site-specific code: selectors | HTTP, database |
| `src/scraper/crawler.py` | the pagination loop and stop reasons | parsing details |
| `src/scraper/storage.py` | SQLite schema, upserts, cache | HTTP |
| `src/scraper/report.py` | summary dict + 4 renderers | crawling |
| `src/testsite/` | the practice site, answer key, hostile routes | scraper code |
| `evals/` | measurements; `run_all.py` | — |

## Rules

1. **Never weaken politeness.** No default `min_delay_s` below 1.0, no removing the CLI's public-host delay check, no auto-following redirects, no skipping robots checks on redirect hops.
2. **Never edit `evals/gold/cases.py` to make a case pass.** It's frozen. Add new cases to a new file with its own first-run result recorded.
3. **Change parsing → bump `BooksProfile.version`**, or 304'd pages will keep stale values.
4. **Every bug fix gets a regression test** named after the behaviour, not the bug.
5. **Numbers in docs come from `evals/results/`.** After changing behaviour, run `make eval` and update prose that quotes numbers (README, POSTMORTEM, DEMO).
6. **Don't run evals or tests against real websites.** Use `testsite`. The CLI is for real sites, at ≥ 0.5 s delay.
7. A new defence needs: a `Settings` switch, an attack in `attack_eval.py`, and an ablation proving the attack lands when the switch is off.
8. Money is integer pence. Never `float`.
