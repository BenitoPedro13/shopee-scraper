# Shopee Scraper (MVP)

Study project for scraping public data from Shopee. Beyond a Playwright MVP, this project prioritizes a CDP (Chrome DevTools Protocol) strategy to capture, from a real Chrome, the API responses used by the page (e.g., PDP), reducing anti‑bot detection.

## Requirements
- Python 3.10+
- macOS/Linux/Windows

## Installation
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
# Install the Playwright browser (Chromium) inside the workspace
PLAYWRIGHT_BROWSERS_PATH=.pw-browsers \
  .venv/bin/python -m playwright install chromium
```

## Configuration
Create a `.env` from `.env.example`:
```env
SHOPEE_DOMAIN=shopee.com.br
HEADLESS=false
STORAGE_STATE=storage_state.json
USER_DATA_DIR=.user-data
DATA_DIR=data
# Optional: profile name to isolate accounts
PROFILE_NAME=br_account_01
LOCALE=pt-BR
TIMEZONE=America/Sao_Paulo
REQUESTS_PER_MINUTE=60
MIN_DELAY=1.0
MAX_DELAY=2.5
PROXY_URL=
USE_PERSISTENT_CONTEXT_FOR_SEARCH=true
DISABLE_3PC_PHASEOUT=true
CDP_PORT=9222
CDP_FILTER_PATTERNS=
```

## Approach (CDP)
- Why CDP: Shopee uses ML + a security SDK with dynamic fingerprinting and cryptographic headers. Instead of detectable automation, we passively observe traffic via CDP.
- Flow: discover product URLs (PDP) → open PDP in Chrome with remote debugging → capture `/api/v4/pdp/get_pc` via CDP → export.
- Real session: use `USER_DATA_DIR` and, ideally, a residential proxy aligned to the region.
  - If `PROXY_URL` is set, Chrome launches with `--proxy-server=...`.
  - Many providers label endpoints “HTTPS proxy”; Chrome flag expects `http://host:port` (we map `https://` → `http://`).
  - Credentials in the URL (`user:pass@host:port`) are stripped from the flag; Chrome will prompt (or use provider IP allow‑listing).
  - CDP aligns `Accept-Language` and `timezone` to `.env` settings.
  - Use `PROFILE_NAME` to isolate directories per account: `.user-data/profiles/<PROFILE_NAME>`.
  - Exports: Pydantic normalization; global dedup by `(shop_id,item_id)` across PDP and Search exports.

## Quickstart (CLI)
```bash
# Validate environment (domain/locale/timezone/proxy/profile)
python cli.py env-validate

# Profiles (isolate sessions and proxies per account)
python cli.py profiles list
python cli.py profiles create br_01
python cli.py profiles use br_01

# Headful login (Playwright) or real Chrome login (CDP profile)
python cli.py login
python cli.py cdp-login

# Discovery (Playwright baseline)
python cli.py search --keyword "bluetooth headphones"

# CDP Product (PDP) capture
python cli.py cdp-pdp "https://shopee.com.br/some-product" --timeout 25
python cli.py cdp-pdp "https://shopee.com.br/some-product" --no-launch --timeout 25  # attach to existing Chrome
# Export normalized PDP data from latest JSONL
python cli.py cdp-export
python cli.py cdp-export data/cdp_pdp_1755508732.jsonl

# CDP Search/List capture
python cli.py cdp-search --keyword "dog toy" --timeout 25  # capture + export
python cli.py cdp-search --keyword "dog toy" --no-launch --no-export  # capture only
python cli.py cdp-search --keyword "dog toy" -p 5 --timeout 12  # pages: 0..4
python cli.py cdp-search --keyword "dog toy" -p 3 --start-page 2  # start from page 2
python cli.py cdp-search --keyword "dog toy" --all-pages --timeout 10  # until no new responses (with safety limit)
python cli.py cdp-search -k "batman" --soft-circuit --circuit-inactivity 12  # softer circuit breaker

# Enrich search export with real PDP data (batch)
python cli.py cdp-enrich-search --launch
# Tip (proxies with auth prompt):
# 1) Start one authenticated session via: python cli.py cdp-login
# 2) Run batches attached to the same instance: --no-launch
python cli.py cdp-enrich-search data/cdp_search_17555_export.json --launch --per-timeout 12 --pause 0.6
python cli.py cdp-enrich-search --soft-circuit --circuit-inactivity 12

# Metrics & Queue
python cli.py metrics summary
python cli.py metrics summary --hours 24 --profile br_01
python cli.py metrics export
python cli.py queue add-search -k "batman" -p 5
python cli.py queue add-enrich --concurrency 6 --per-timeout 12
python cli.py queue list
python cli.py queue run --max-tasks 5
```

Notes
- `search` is for basic discovery; robust data collection uses CDP on PDPs.
- For consistency, you can use `cdp-login` + `cdp-search` and skip Playwright completely.
- CDP output: `data/cdp_pdp_<timestamp>.jsonl` (one line per captured response with url/status/headers/body).
  - For search: `data/cdp_search_<timestamp>.jsonl` + exports `_export.json`/`_export.csv`.
  - Health & circuit breaker: on block signals, the profile is marked degraded at `data/session_status/<profile>.json` and the command fails. Signals include:
    - Navigation to verification/login pages (e.g., `/verify/captcha`, `/account/login`, contains `captcha`).
    - 403/429 responses on filtered APIs.
    - Prolonged network inactivity without relevant responses.
  - Rate limiting: CDP navigations are limited by `REQUESTS_PER_MINUTE`.
  - Recycling: if `PAGES_PER_SESSION` > 0 and `--launch` is active, long batches are split into smaller sessions (Chrome relaunched between chunks) and JSONLs are concatenated. A short random cooldown (2–5s) reduces reconnection patterns.
  - Profiles: use `python cli.py profiles use <name>` to set `PROFILE_NAME` and isolate cookies/cache per account. Validate env via `python cli.py env-validate`.

## Recent Protections (CDP)
- Circuit breaker: early abort on CAPTCHA/login/inactivity/403‑429; marks session as degraded.
- Backoff: exponential retries with jitter for `Page.navigate`, `Network.getResponseBody`, and CDP domain enable.
- Cooldown: random pause between sessions when recycling via `PAGES_PER_SESSION`.
- JSON logs: minimal events/metrics written to `data/logs/events.jsonl` (includes counters like navigations, matches, blocks, and duration per run).

## Concurrency & Circuit Tuning
- Max concurrency: limit via CLI (`--concurrency`) and env `CDP_MAX_CONCURRENCY` (default 12).
- Per‑tab time: adjust `--per-timeout` (PDP batch) or `--timeout` (Search/CDP).
- Stagger: use `--stagger` (e.g., 0.8–1.0s) to reduce bursts.
- Circuit: by default aborts on blocks/inactivity; can be softened via env:
  - `CDP_INACTIVITY_S` (default 8.0) — inactivity window before signaling a block.
  - `CDP_CIRCUIT_ENABLED` (true/false) — disable immediate abort (soft mode; log and continue).

## Structured Metrics
- Reports: `python cli.py metrics summary [--hours N] [--profile X] [--proxy URL]`.
- Metrics: success rate per run, average duration, blocks (reasons) and counters (navigations, pages), by profile/proxy and overall.
- Export: `python cli.py metrics export` produces `data/metrics/summary.csv` and `summary.json`. See `docs/metrics_example.ipynb` for quick charts (pandas/matplotlib).

## Paged Search (value and limits)
- Value: broader coverage (long‑tail), less first‑page bias, more PDP URLs to enrich.
- Modes: `-p/--pages` for N pages; `--all-pages` runs until no new responses appear for a few consecutive pages (with `--max-pages` safety).
- Limits: higher block risk — use rate limiting and the circuit breaker; keep profiles/proxies coherent with the region; prefer short rounds with recycling.

## Project Layout
```
.
├── cli.py
├── requirements.txt
├── .env.example
├── src/
│   └── shopee_scraper/
│       ├── __init__.py
│       ├── config.py
│       ├── session.py
│       ├── search.py
│       ├── utils.py
│       └── cdp/
│           ├── __init__.py
│           └── collector.py
├── data/
│   └── .gitkeep
└── docs/
    ├── ARCHITECTURE_PLAN.md
    ├── ANTIBOT_CAPTCHA_NOTE.md
    ├── REQUIREMENTS_STATUS.md
    ├── SCALING_ROADMAP.md
    ├── MULTISITE_ADAPTERS.md
    ├── PRODUCT_HANDBOOK.md
    └── BACKLOG.md
```

## Safety & Compliance
- Collect only public data; respect robots.txt and ToS.
- Avoid PII; use conservative limits; keep one IP per session/profile.

## Unified Documentation
- Product handbook: `docs/PRODUCT_HANDBOOK.md` (vision, current state, goals, roadmap, operations)
- Structured backlog: `docs/BACKLOG.md` (milestones, tasks, priority, complexity, tags)
- Architecture: `docs/ARCHITECTURE_PLAN.md` (with 2025‑08 addendum)
- Requirements & status: `docs/REQUIREMENTS_STATUS.md` (with scaling addendum)
- Scaling roadmap: `docs/SCALING_ROADMAP.md`
- Multi‑site design: `docs/MULTISITE_ADAPTERS.md`
 - Operations guide: `docs/operations.md` (runbooks and day‑2 operations)

## Tests
```bash
pytest -q
```
- Initial test scope: IO utilities (JSON/CSV) and CDP exporters (PDP/Search normalization). Tests avoid opening a browser.
