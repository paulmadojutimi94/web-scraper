"""Reports: turn the database into something a person reads.

build_summary() runs the SQL and returns one plain dict. The writers render
that dict four ways, so every format always shows the same numbers:
  summary.json  for machines (and the evals)
  report.md     for GitHub / a terminal
  report.html   for a browser (every scraped string HTML-escaped)
  books.csv     for Excel (every cell defused against formula injection)
"""

from __future__ import annotations

import csv
import html
import json
import math
import sqlite3
from pathlib import Path

from .config import Settings

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile: p95 = the value 95% of samples are at or below."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def pounds(pence: float | None) -> str:
    return "-" if pence is None else f"£{pence / 100:,.2f}"


def build_summary(conn: sqlite3.Connection, run_id: int | None = None) -> dict:
    conn.row_factory = sqlite3.Row
    if run_id is None:
        run_id = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()[0]
    run = dict(conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())
    run.pop("settings_json", None)

    fetches = [dict(r) for r in conn.execute("SELECT * FROM fetch_log WHERE run_id = ?", (run_id,))]
    outcomes: dict[str, int] = {}
    for f in fetches:
        outcomes[f["outcome"]] = outcomes.get(f["outcome"], 0) + 1
    good = [f["elapsed_ms"] for f in fetches if f["outcome"] in ("ok", "not_modified")]
    fresh = outcomes.get("ok", 0)
    cached = outcomes.get("not_modified", 0)
    crawl = {
        "requests": len(fetches),
        "http_attempts": sum(f["attempts"] for f in fetches),
        "retries": sum(f["retries"] for f in fetches),
        "redirects": sum(f["redirects"] for f in fetches),
        "outcomes": outcomes,
        "bytes_downloaded": sum(f["bytes"] for f in fetches),
        "latency_ms_p50": _r(percentile(good, 50)),
        "latency_ms_p95": _r(percentile(good, 95)),
        "cache_hit_rate": round(cached / (fresh + cached), 3) if fresh + cached else None,
    }

    books = [dict(r) for r in conn.execute(
        "SELECT * FROM books WHERE last_seen_run = ? ORDER BY title", (run_id,))]
    prices = [b["price_pence"] for b in books]
    by_category = [dict(r) for r in conn.execute(
        "SELECT category, COUNT(*) AS books, ROUND(AVG(price_pence)) AS avg_price_pence "
        "FROM books WHERE last_seen_run = ? GROUP BY category ORDER BY books DESC, category LIMIT 10",
        (run_id,))]
    ratings = {str(k): 0 for k in range(1, 6)}
    for b in books:
        if b["rating"]:
            ratings[str(b["rating"])] += 1
    in_stock = [b for b in books if b["in_stock"]]
    catalogue = {
        "books": len(books),
        "categories": len({b["category"] for b in books}),
        "price_min_pence": min(prices) if prices else None,
        "price_median_pence": percentile(prices, 50),
        "price_mean_pence": round(sum(prices) / len(prices)) if prices else None,
        "price_max_pence": max(prices) if prices else None,
        "rating_counts": ratings,
        "in_stock_pct": round(100 * len(in_stock) / len(books), 1) if books else None,
        "units_in_stock": sum(b["stock_count"] or 0 for b in in_stock),
        "top_categories": by_category,
        "best_value": [  # cheapest 5-star books that are actually in stock
            {"title": b["title"], "price_pence": b["price_pence"], "url": b["url"]}
            for b in sorted((b for b in in_stock if b["rating"] == 5),
                            key=lambda b: (b["price_pence"], b["title"]))[:5]
        ],
    }

    price_changes = [dict(r) for r in conn.execute(
        "SELECT b.title, c.url, CAST(c.old_value AS INTEGER) AS old_pence, "
        "CAST(c.new_value AS INTEGER) AS new_pence FROM changes c JOIN books b ON b.url = c.url "
        "WHERE c.run_id = ? AND c.field = 'price_pence' ORDER BY b.title", (run_id,))]
    change_counts = {r["field"]: r["n"] for r in conn.execute(
        "SELECT field, COUNT(*) AS n FROM changes WHERE run_id = ? GROUP BY field", (run_id,))}
    new_books = conn.execute(
        "SELECT COUNT(*) FROM books WHERE first_seen_run = ?", (run_id,)).fetchone()[0]
    previous_run = conn.execute("SELECT MAX(run_id) FROM runs WHERE run_id < ?", (run_id,)).fetchone()[0]
    gone = []
    if previous_run and run["stop_reason"] == "done":  # only a complete crawl can say what vanished
        gone = [r["title"] for r in conn.execute(
            "SELECT title FROM books WHERE last_seen_run = ? ORDER BY title", (previous_run,))]
    rejects = [dict(r) for r in conn.execute(
        "SELECT url, reasons FROM rejects WHERE run_id = ? ORDER BY url", (run_id,))]

    return {
        "run": run,
        "crawl": crawl,
        "catalogue": catalogue,
        "changes": {"new_books": new_books, "fields_changed": change_counts,
                    "price_changes": price_changes, "gone_since_last_run": gone},
        "rejects": rejects,
        "books": books,
    }


def write_reports(summary: dict, out_dir: str | Path, settings: Settings | None = None) -> list[Path]:
    settings = settings or Settings()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / "summary.json", out / "report.md", out / "report.html", out / "books.csv"]
    public = {k: v for k, v in summary.items() if k != "books"}
    paths[0].write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths[1].write_text(render_markdown(summary), encoding="utf-8")
    paths[2].write_text(render_html(summary, escape=settings.escape_html), encoding="utf-8")
    write_csv(summary["books"], paths[3], guard=settings.guard_formulas)
    return paths


# -- CSV ---------------------------------------------------------------------------------
def defuse(value):
    """'=HYPERLINK(...)' -> "'=HYPERLINK(...)" so Excel shows it as text instead of running it."""
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


def write_csv(books: list[dict], path: Path, guard: bool = True) -> None:
    columns = ["title", "category", "price_pence", "rating", "in_stock", "stock_count", "upc", "url"]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel then reads UTF-8 right
        writer = csv.writer(fh)
        writer.writerow(columns)
        for b in books:
            writer.writerow([defuse(b[c]) if guard else b[c] for c in columns])


# -- Markdown ----------------------------------------------------------------------------
def _md(text) -> str:
    return str(text).replace("|", "\\|")


def render_markdown(s: dict) -> str:
    run, crawl, cat, ch = s["run"], s["crawl"], s["catalogue"], s["changes"]
    lines = [
        f"# Scrape report: run {run['run_id']}",
        "",
        f"`{run['start_url']}` | started {run['started_at']} | finished {run['finished_at']} "
        f"| stopped because: **{run['stop_reason']}**",
        "",
        "## Crawl",
        "",
        "| Requests | HTTP attempts | Retries | Downloaded | Cache hits (304) | p50 | p95 |",
        "|---|---|---|---|---|---|---|",
        f"| {crawl['requests']} | {crawl['http_attempts']} | {crawl['retries']} "
        f"| {crawl['bytes_downloaded'] / 1e6:.2f} MB | {_pct(crawl['cache_hit_rate'])} "
        f"| {crawl['latency_ms_p50']} ms | {crawl['latency_ms_p95']} ms |",
        "",
        "Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(crawl["outcomes"].items())),
        "",
        "## Catalogue",
        "",
        f"**{cat['books']} books** in {cat['categories']} categories. "
        f"Prices {pounds(cat['price_min_pence'])} to {pounds(cat['price_max_pence'])} "
        f"(median {pounds(cat['price_median_pence'])}, mean {pounds(cat['price_mean_pence'])}). "
        f"{cat['in_stock_pct']}% in stock, {cat['units_in_stock']:,} units.",
        "",
        "| Rating | " + " | ".join("★" * int(k) for k in cat["rating_counts"]) + " |",
        "|---|" + "---|" * 5,
        "| Books | " + " | ".join(str(v) for v in cat["rating_counts"].values()) + " |",
        "",
        "### Top categories",
        "",
        "| Category | Books | Average price |",
        "|---|---|---|",
    ]
    lines += [f"| {_md(c['category'])} | {c['books']} | {pounds(c['avg_price_pence'])} |"
              for c in cat["top_categories"]]
    lines += ["", "### Best value: cheapest 5-star books in stock", "", "| Title | Price |", "|---|---|"]
    lines += [f"| {_md(b['title'])} | {pounds(b['price_pence'])} |" for b in cat["best_value"]]
    lines += ["", "## Changes since the last run", "",
              f"{ch['new_books']} new books; fields changed: "
              + (", ".join(f"{k} {v}" for k, v in sorted(ch["fields_changed"].items())) or "none")
              + f"; {len(ch['gone_since_last_run'])} gone.", ""]
    if ch["price_changes"]:
        lines += ["| Title | Was | Now | Change |", "|---|---|---|---|"]
        for p in ch["price_changes"][:25]:
            delta = 100 * (p["new_pence"] - p["old_pence"]) / p["old_pence"]
            lines.append(f"| {_md(p['title'])} | {pounds(p['old_pence'])} | {pounds(p['new_pence'])} "
                         f"| {delta:+.1f}% |")
        if len(ch["price_changes"]) > 25:
            lines.append(f"| ...and {len(ch['price_changes']) - 25} more | | | |")
        lines.append("")
    lines += ["## Rejected pages", ""]
    lines += [f"- {r['url']}: {r['reasons']}" for r in s["rejects"]] or ["None."]
    return "\n".join(lines) + "\n"


def _pct(value) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"


# -- HTML --------------------------------------------------------------------------------
def render_html(s: dict, escape: bool = True) -> str:
    e = html.escape if escape else (lambda x: str(x))
    cat, crawl, ch = s["catalogue"], s["crawl"], s["changes"]
    top = max(cat["rating_counts"].values()) or 1
    bars = "".join(
        f'<div class="bar"><span>{"★" * int(k)}</span><i style="width:{60 * v / top:.1f}%"></i>'
        f"<b>{v}</b></div>" for k, v in cat["rating_counts"].items())
    rows = "".join(
        f"<tr><td><a href=\"{e(b['url'])}\">{e(b['title'])}</a></td><td>{e(b['category'])}</td>"
        f"<td>{pounds(b['price_pence'])}</td><td>{b['rating'] or '-'}</td>"
        f"<td>{b['stock_count'] if b['in_stock'] else 'out'}</td></tr>"
        for b in s["books"][:200])
    changes = "".join(
        f"<tr><td>{e(p['title'])}</td><td>{pounds(p['old_pence'])}</td><td>{pounds(p['new_pence'])}</td></tr>"
        for p in ch["price_changes"][:50]) or '<tr><td colspan="3">No price changes.</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Scrape report: run {s['run']['run_id']}</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1d1d1f}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem}}
.kpi{{border:1px solid #ddd;border-radius:8px;padding:.75rem}} .kpi b{{display:block;font-size:1.4rem}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}
td,th{{border-bottom:1px solid #eee;padding:.3rem .5rem;text-align:left}}
.bar{{display:flex;align-items:center;gap:.5rem}} .bar span{{width:5rem}}
.bar i{{height:.9rem;background:#4f6bed;border-radius:3px}}
</style></head><body>
<h1>Scrape report: run {s['run']['run_id']}</h1>
<p><code>{e(s['run']['start_url'])}</code>, stopped because <b>{e(s['run']['stop_reason'])}</b></p>
<div class="kpis">
<div class="kpi"><b>{cat['books']}</b>books</div>
<div class="kpi"><b>{pounds(cat['price_median_pence'])}</b>median price</div>
<div class="kpi"><b>{cat['in_stock_pct']}%</b>in stock</div>
<div class="kpi"><b>{crawl['requests']}</b>requests ({crawl['retries']} retries)</div>
</div>
<h2>Ratings</h2>{bars}
<h2>Price changes since last run</h2>
<table><tr><th>Title</th><th>Was</th><th>Now</th></tr>{changes}</table>
<h2>Books (first 200)</h2>
<table><tr><th>Title</th><th>Category</th><th>Price</th><th>Rating</th><th>Stock</th></tr>{rows}</table>
</body></html>
"""


def _r(value):
    return None if value is None else round(value, 1)
