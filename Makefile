PY ?= python3
export PYTHONPATH := src

.PHONY: test eval eval-check lint demo serve video

test:          ## 78 tests, ~15 s
	$(PY) -m pytest -q

eval:          ## every eval (~4 min); rewrites the README results table
	$(PY) evals/run_all.py

eval-check:    ## CI: fail if README's table disagrees with evals/results/
	$(PY) evals/run_all.py --check

lint:
	ruff check src tests evals scripts

demo:          ## crawl the local test site, change it, crawl again, write reports to examples/
	$(PY) scripts/demo.py

serve:         ## run the practice site on http://127.0.0.1:8000/catalogue/page-1.html
	$(PY) -m scraper serve-testsite --port 8000

video:         ## rebuild docs/demo/web-scraper-demo.{gif,mp4} from real output
	$(PY) docs/demo/make_video.py
