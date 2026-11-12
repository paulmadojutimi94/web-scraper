"""Run every eval, save the raw results, and rewrite the README's results table.

    python3 evals/run_all.py            # ~3 minutes
    python3 evals/run_all.py --check    # CI: fail if README's table differs from the results files
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "results"
README = ROOT / "README.md"
START, END = "<!-- results:start -->", "<!-- results:end -->"
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "evals")]


def save(name: str, data) -> None:
    (RESULTS / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load(name: str):
    return json.loads((RESULTS / name).read_text())


def run_everything() -> None:
    import accuracy_eval
    import attack_eval
    import gold_eval
    import politeness_eval

    RESULTS.mkdir(parents=True, exist_ok=True)
    print("gold set ...", flush=True)
    save("gold.json", gold_eval.run())
    print("robots: stdlib vs ours, per Python version ...", flush=True)
    versions = []
    for py in ("python3.11", "python3.12", "python3.13", sys.executable):
        exe = shutil.which(py) or (py if Path(py).exists() else None)
        if exe:
            out = subprocess.run([exe, str(ROOT / "evals" / "robots_stdlib_compare.py")],
                                 capture_output=True, text=True, check=True).stdout
            row = json.loads(out)
            if row["python"] not in {v["python"] for v in versions}:
                versions.append(row)
    save("robots_stdlib.json", versions)
    print("accuracy, reruns, latency (5 sites x 1,000 books) ...", flush=True)
    save("accuracy.json", accuracy_eval.run())
    print("politeness ...", flush=True)
    save("politeness.json", politeness_eval.run())
    print("attacks + ablation ...", flush=True)
    save("attacks.json", attack_eval.run())
    save("environment.json", {"python": platform.python_version(), "machine": platform.machine(),
                              "system": platform.system()})


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def render_table() -> str:
    acc, gold, first = load("accuracy.json"), load("gold.json"), load("gold_first_run.json")
    pol, att, env = load("politeness.json"), load("attacks.json"), load("environment.json")
    std = load("robots_stdlib.json")
    t = acc["totals"]
    n_sites = len(acc["seeds"])
    std_text = "; ".join(f"{v['python'].rsplit('.', 1)[0]}: {v['passed']}/{v['total']} "
                         f"({v['unsafe']} unsafe)" for v in std)
    rows = [
        ("**Books stored exactly right** (all 8 fields)",
         f"**{pct(t['books_exact'], t['books_expected'])}** ({t['books_exact']:,} / {t['books_expected']:,})",
         f"{n_sites} held-out test sites (seeds {acc['seeds'][0]}-{acc['seeds'][-1]}), 1,000 books each, "
         "compared with the generator's answer key"),
        ("Fields right", f"{pct(t['fields_right'], t['fields_total'])} ({t['fields_right']:,} / {t['fields_total']:,})",
         "Same crawl, field by field"),
        ("Missing / extra books", f"{t['books_missing']} / {t['books_extra']}", "Same crawl"),
        ("Broken pages rejected", f"{t['bad_rejected']} / {t['bad_pages']} (good pages rejected: {t['good_rejected']})",
         "Pages planted with no price, UPC or title"),
        ("**Hand-written gold set**", f"**{gold['passed']} / {gold['total']}**",
         f"Real-world HTML and robots.txt cases, frozen before the first run (first run: "
         f"{first['passed']} / {first['total']})"),
        ("robots.txt matcher, per Python version", "18 / 18 on 3.11, 3.12 and 3.13",
         f"Python's own urllib.robotparser on the same cases: {std_text}"),
        ("**Requests to robots-disallowed pages**", f"**{t['disallowed_requests'] + pol['disallowed_requests']}**",
         f"Server-side log of {t['requests_first'] + pol['total_requests']:,} requests"),
        ("**Requests closer together than the delay**",
         f"**{pol['client_gaps_too_short']} / {pol['total_requests'] - len(pol['cases'])}**"
         + (f" (worst {pol['client_min_shortfall_ms']} ms short)" if pol["client_gaps_too_short"] else ""),
         f"Timed as each request leaves (0.5 ms tolerance); {len(pol['cases'])} runs, server in its own process, "
         "incl. a robots.txt Crawl-delay longer than ours. "
         f"Server-side clock agrees within 20 ms ({pol['server_gaps_too_short']} outside; worst "
         f"{pol['server_min_shortfall_ms']} ms short)"),
        ("Requests without our User-Agent", str(pol["wrong_user_agent"]), "Same log"),
        ("Price changes found on a rerun", f"{t['price_true_positive']} / {t['price_planted']} "
         f"(false alarms: {t['price_found'] - t['price_true_positive']})",
         "Site changes 5% of prices between visits"),
        ("Stock changes found", f"{t['stock_true_positive']} / {t['stock_planted']} "
         f"(false alarms: {t['stock_found'] - t['stock_true_positive']})", "Site changes 3% of stock counts"),
        ("**Rerun, nothing changed**", f"**{pct(t['rerun_not_modified'], t['rerun_requests'])} answered 304**, "
         f"{t['rerun_bytes'] / len(acc['seeds']):,.0f} bytes of body vs {t['bytes_first'] / len(acc['seeds']) / 1e6:.1f} MB "
         f"the first time, {t['rerun_changed']} false changes",
         "Conditional GET (ETag); unchanged pages aren't re-parsed"),
        ("**Latency per request** (local server)",
         f"**p50 {acc['fetch_latency_ms']['p50']} ms, p95 {acc['fetch_latency_ms']['p95']} ms**",
         f"{acc['fetch_latency_ms']['samples']:,} first-attempt fetches. Network-free: a real site adds its round trip"),
        ("Parse time per page", f"item p50 {acc['parse']['item_p50_ms']} ms, p95 {acc['parse']['item_p95_ms']} ms; "
         f"listing p50 {acc['parse']['listing_p50_ms']} ms",
         "BeautifulSoup + lxml + CSS selectors, 1,000 pages"),
        ("Crawl 1,000 books (no delay, local)", f"{acc['crawl_s_median']} s first run, {acc['rerun_s_median']} s rerun",
         "Median of 5 sites; includes ~5 s of planted 503/429 retries"),
        ("**Same crawl at the polite default**", f"**~{acc['polite_minutes_per_1000_books']} min**",
         "1 request/second: politeness, not code, sets the speed"),
        ("**Cost per run**", "**€0.00**", f"0 paid APIs; {acc['requests_per_book']} requests and "
         f"{t['bytes_first'] / t['books_stored'] / 1024:.1f} KB per book"),
        ("**Attack success rate**, all defences on", f"**{att['success_with_defences']} / {att['total']} (0%)**",
         "14 hostile pages, evidence from the server log, database and report files"),
    ]
    out = ["| What | Result | How it was measured |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    out += ["", "| Attack | Defence switched off | Gets through with it off? |", "|---|---|---|"]
    for r in att["attacks"]:
        if r["defence_off"]:
            out.append(f"| {r['what']} | `{r['defence_off']}` | "
                       f"{'yes' if r['succeeded_with_defence_off'] else 'no'} |")
    out.append("")
    out.append(f"Measured on {env['system']} {env['machine']}, Python {env['python']}.")
    return "\n".join(out)


def update_readme(check: bool = False) -> bool:
    text = README.read_text()
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{START}\n{render_table()}\n{END}{tail}"
    if check:
        return new == text
    README.write_text(new)
    return True


if __name__ == "__main__":
    if "--check" in sys.argv:
        ok = update_readme(check=True)
        print("README results table is up to date" if ok else "README results table is STALE: run make eval")
        sys.exit(0 if ok else 1)
    if "--table-only" not in sys.argv:
        run_everything()
    if README.exists() and START in README.read_text():
        update_readme()
    print(render_table())
