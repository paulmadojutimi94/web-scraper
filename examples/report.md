# Scrape report: run 3

`http://127.0.0.1:8000/catalogue/page-1.html` | started 2026-11-12T16:37:40+00:00 | finished 2026-11-12T16:37:42+00:00 | stopped because: **done**

## Crawl

| Requests | HTTP attempts | Retries | Downloaded | Cache hits (304) | p50 | p95 |
|---|---|---|---|---|---|---|
| 1050 | 1052 | 0 | 0.64 MB | 88% | 1.4 ms | 1.9 ms |

Outcomes: not_modified 918, ok 122, robots_blocked 10

## Catalogue

**982 books** in 25 categories. Prices £10.04 to £4,460.87 (median £37.30, mean £74.92). 86.5% in stock, 9,494 units.

| Rating | ★ | ★★ | ★★★ | ★★★★ | ★★★★★ |
|---|---|---|---|---|---|
| Books | 181 | 192 | 196 | 212 | 201 |

### Top categories

| Category | Books | Average price |
|---|---|---|
| Classics | 49 | £72.78 |
| Poetry | 49 | £34.17 |
| Food and Drink | 48 | £31.26 |
| Music | 45 | £128.67 |
| Young Adult | 45 | £88.80 |
| Health | 44 | £35.90 |
| Psychology | 44 | £233.87 |
| Science Fiction | 44 | £129.37 |
| Art | 43 | £96.94 |
| Childrens | 42 | £79.09 |

### Best value: cheapest 5-star books in stock

| Title | Price |
|---|---|
| The Northern River (Revised Edition) | £10.17 |
| The Broken Letters | £10.75 |
| The Lonely River (A Novel) | £11.21 |
| The Broken River | £11.28 |
| The Paper Winter | £12.10 |

## Changes since the last run

0 new books; fields changed: in_stock 6, price_pence 50, stock_count 32; 0 gone.

| Title | Was | Now | Change |
|---|---|---|---|
| Story Journey Family Journey Garden Garden River House Family An Sea | £23.71 | £27.60 | +16.4% |
| The Broken Harbour | £56.44 | £64.78 | +14.8% |
| The Broken Lighthouse (Book 2) | £48.47 | £55.65 | +14.8% |
| The Broken Winter | £46.31 | £51.12 | +10.4% |
| The Burning Daughter (Revised Edition) | £44.79 | £37.70 | -15.8% |
| The Burning Empire | £33.97 | £31.76 | -6.5% |
| The Burning Fox | £4,130.99 | £3,873.55 | -6.2% |
| The Burning Harbour (A Novel) | £29.52 | £35.09 | +18.9% |
| The Burning Kingdom (Book 2) | £37.80 | £45.21 | +19.6% |
| The Burning Orchard | £30.01 | £34.80 | +16.0% |
| The Burning River (Revised Edition) | £46.50 | £46.71 | +0.5% |
| The Crimson Library (A Novel) | £44.34 | £49.57 | +11.8% |
| The Crimson Station (Book 2) | £44.97 | £44.16 | -1.8% |
| The Distant Fox | £27.79 | £22.54 | -18.9% |
| The Distant Library (Book 2) | £49.71 | £53.99 | +8.6% |
| The Electric Harbour | £44.16 | £38.79 | -12.2% |
| The Golden Cartographer (A Novel) | £34.14 | £39.07 | +14.4% |
| The Golden Harbour | £53.98 | £48.70 | -9.8% |
| The Golden Orchard (Book 2) | £44.75 | £37.30 | -16.6% |
| The Golden Winter | £48.38 | £46.60 | -3.7% |
| The Hidden Empire | £49.98 | £51.58 | +3.2% |
| The Hidden Garden | £18.98 | £16.57 | -12.7% |
| The Hidden Library (A Novel) | £19.79 | £17.64 | -10.9% |
| The Hungry Cartographer | £34.27 | £31.87 | -7.0% |
| The Hungry Machine | £42.88 | £49.35 | +15.1% |
| ...and 25 more | | | |

## Rejected pages

- http://127.0.0.1:8000/catalogue/the-distant-river_184/index.html: missing upc
- http://127.0.0.1:8000/catalogue/the-electric-station_281/index.html: missing title
- http://127.0.0.1:8000/catalogue/the-hidden-fox_699/index.html: missing upc
- http://127.0.0.1:8000/catalogue/the-hidden-river_488/index.html: missing price_pence
- http://127.0.0.1:8000/catalogue/the-last-winter_213/index.html: missing upc
- http://127.0.0.1:8000/catalogue/the-lonely-station_16/index.html: missing price_pence
- http://127.0.0.1:8000/catalogue/the-quiet-letters_960/index.html: missing price_pence
- http://127.0.0.1:8000/catalogue/voice-dark-garden-an-road-story-road-time-night-an-sea-of-lo_583/index.html: missing title
