"""Run the frozen gold set and report every case that fails."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "evals")]

from gold.cases import CRAWL_DELAY_CASES, PARSE_CASES, ROBOTS_CASES, URL  # noqa: E402
from scraper.profiles.books import BooksProfile  # noqa: E402
from scraper.robots import parse_robots  # noqa: E402

UA = "web-scraper/0.1"


def run_parse(case: dict) -> tuple[bool, str]:
    profile = BooksProfile()
    body = case["html"].encode(case.get("encoding_bytes", "utf-8"))
    encoding = case.get("header_charset")
    if case["kind"] == "listing":
        page = profile.parse_listing(body, encoding, case["url"])
        got = {"item_urls": page.item_urls, "next_url": page.next_url}
    else:
        result = profile.parse_item(body, encoding, URL)
        if case["expect"] == "reject":
            return result.item is None, f"reasons={result.reasons}" if result.item is None else "accepted"
        if result.item is None:
            return False, f"rejected: {result.reasons}"
        got = result.item
    wrong = {k: (v, got.get(k)) for k, v in case["expect"].items() if got.get(k) != v}
    return not wrong, "; ".join(f"{k}: expected {e!r}, got {g!r}" for k, (e, g) in wrong.items())


def run() -> dict:
    failures = []
    passed = 0
    for case in PARSE_CASES:
        try:
            ok, detail = run_parse(case)
        except Exception as exc:  # a crash is a failure, not a stopped eval
            ok, detail = False, f"crashed: {type(exc).__name__}: {exc}"
        passed += ok
        if not ok:
            failures.append({"id": case["id"], "detail": detail})
    for case_id, text, path, expected in ROBOTS_CASES:
        got = parse_robots(200, text).allowed("http://shop.test" + path, UA)
        passed += got == expected
        if got != expected:
            unsafe = got and not expected
            failures.append({"id": case_id, "detail": f"expected allowed={expected}, got {got}"
                             + (" (UNSAFE: fetches a disallowed page)" if unsafe else " (over-cautious)")})
    for case_id, text, expected in CRAWL_DELAY_CASES:
        got = parse_robots(200, text).crawl_delay(UA)
        passed += got == expected
        if got != expected:
            failures.append({"id": case_id, "detail": f"expected crawl-delay {expected}, got {got}"})
    total = len(PARSE_CASES) + len(ROBOTS_CASES) + len(CRAWL_DELAY_CASES)
    return {"passed": passed, "total": total, "failures": failures}


if __name__ == "__main__":
    result = run()
    print(f"gold set: {result['passed']} / {result['total']}")
    for f in result["failures"]:
        print(f"  FAIL {f['id']}: {f['detail']}")
    if "--save" in sys.argv:
        out = ROOT / "evals" / "results" / sys.argv[sys.argv.index("--save") + 1]
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
