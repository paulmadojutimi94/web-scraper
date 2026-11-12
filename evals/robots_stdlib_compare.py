"""How does Python's own urllib.robotparser do on the robots gold cases, per Python version?

Run with any interpreter: `python3.11 evals/robots_stdlib_compare.py`. Prints one JSON line.
Needs only the standard library, so it works on Pythons without our dependencies installed.
"""

import json
import sys
from pathlib import Path
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gold.cases import CRAWL_DELAY_CASES, ROBOTS_CASES  # noqa: E402

UA = "web-scraper/0.1"
failures = []
for case_id, text, path, expected in ROBOTS_CASES:
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    got = rp.can_fetch(UA, "http://shop.test" + path)
    if got != expected:
        failures.append(case_id + (" (unsafe)" if got and not expected else ""))
for case_id, text, expected in CRAWL_DELAY_CASES:
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    got = rp.crawl_delay(UA)
    if (float(got) if got is not None else None) != expected:
        failures.append(case_id)
total = len(ROBOTS_CASES) + len(CRAWL_DELAY_CASES)
print(json.dumps({"python": sys.version.split()[0], "passed": total - len(failures), "total": total,
                  "unsafe": sum("unsafe" in f for f in failures), "failures": failures}))
