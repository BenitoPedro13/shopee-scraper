Shopee Scraper — Architecture Plan (2025)

Vision
- Evolutionary academic project to collect public Shopee data with a focus on compliance (no PII, respect robots.txt/ToS), anti‑bot robustness, and maintainability.

Objectives
- Collect public data (search, product, shop, reviews) under an authenticated session.
- Persist session to minimize recurring OTP/CAPTCHA.
- Reduce blocks with throttling, delays, proxies, and isolated profiles.
- Reproducibility: configuration via .env, single CLI, logs, and metrics.

Technical Stack
- Python 3.10+; Playwright (basic UI automation) and real Chrome via CDP for network interception.
- python‑dotenv (config), pydantic (Settings/Schema), tenacity (retries), loguru (logging), pandas (CSV), rich/typer (CLI UX).
- CDP client (pychrome/pycdp) to capture API calls resiliently.
- Future: Kameleo (anti‑detect), 2Captcha/Anti‑Captcha (CAPTCHA), OnlineSim/Grizzly (OTP), SQLite/Postgres (persistence).

Phase 1 — Minimal MVP (headful, persisted session)
- Manual login via Playwright (headful) and save storage_state.json.
- Initial search and basic card extraction (title, price, sold, URL) — aware of anti‑bot limits.
- Simple JSON/CSV exports in data/.
- Controls: wait_for_selector, wait_until=networkidle, random delays, generous timeouts.
- CLI: login and search commands.

Phase 2 — Product and Data Model
- Product page: title, price, variations, stock, seller, rating, images.
- Pydantic schemas for validation/normalization.
- Deduplication by (shopid, itemid) whenever available.
- Pagination/controlled scroll in search/category.

Phase 3 — Resilience and Block Signals
- Retries with exponential backoff (429/5xx) using tenacity.
- Detect login wall/CAPTCHA/empty layout → mark session as degraded.
- Throttling: ~1–2 req/s per profile, minute budgets.
- Session health‑check before running batches.
- Human behavior (mouse/scroll/typing/dwell) and locale/timezone/UA consistency.

Phase 4 — Sessions, Profiles, and Proxies
- Multiple isolated profiles (one Chrome profile per instance/account).
- One IP (residential/mobile proxy) per profile; geolocation coherent with the domain (e.g., BR → shopee.com.br).
- Controlled IP rotation (avoid changes mid‑session; recycle between batches).
- Domain ↔ region/IP mapping; sticky sessions when needed.

Phase 5 — CAPTCHA and OTP
- Integrate with 2Captcha/Anti‑Captcha (manual fallback).
- SMS API for registration/authentication when needed.
- Aggressive session reuse to reduce OTP/CAPTCHA costs.

Phase 6 — Scale and Orchestration
- Scheduler/queue (Celery/RQ + Redis or simple Python pipeline).
- Safe concurrency: limits per profile/account/IP.
- Metrics: success rate, pages/hour, bans/hour, average latency, transient vs fatal errors.
- Structured logs (JSON) with levels (info, warn, error).

Phase 6 — CDP Interception (priority approach)
- Launch real Chrome with --remote-debugging-port=9222 using persistent profile and proxy.
- Connect via CDP (pychrome/pycdp); enable Network domain; collect requestWillBeSent/responseReceived/loadingFinished.
- Filter relevant endpoints (e.g., /api/v4/pdp/get_pc) and fetch body with Network.getResponseBody.
- Navigate via human‑like UI (home → category → PDP) and record metadata (timing, URL, headers). Avoid detectable JS injection.
- Align Accept‑Language/timezone/UA; ensure cookies/3P cookies and consent.

Phase 7 — Scale and Orchestration (CDP)
- Multiple isolated Chrome instances (profile, proxy, session) in parallel.
- Recycle instances after N pages (50–100) to avoid pattern accumulation.
- Scheduler/queue (Celery/RQ) to distribute URLs across instances/locations.
- Metrics: success rate, bans/hour, latency; structured logs.

Phase 8 — Mobile Alternatives (strategic fallback)
- Intercept native app API (protocol reverse; extract endpoints and mobile tokens).
- Android emulator (Genymotion) + logged‑in mobile Chrome + capture via ADB (system‑level).
- Maintain at least one mobile track in parallel with CDP for long‑term resilience.

Phase 9 — Anti‑detect (optional)
- Kameleo/anti‑detect + Chrome/Playwright/CDP: realistic fingerprint, aligned timezone/locale, persistent profiles.
- Profile management via local API; reuse without manual cookie export.

Phase 10 — Persistence and Data Delivery
- Files: JSON/CSV per batch in data/.
- DB: SQLite (local) or Postgres; upsert by (shopid, itemid).
- Indexes for queries by category/keyword/date.

Phase 11 — Observability and Maintenance
- Simple dashboard (CLI/Notebook) for metrics and samples.
- Selector break alerts; daily smoke tests.
- Routine selector updates via config/feature flags.

Phase 12 — Compliance and Security
- No PII; respect robots.txt and ToS.
- Conservative rate limits; circuit breakers upon block detection.
- Secrets in .env; never version storage_state.json.

Directory Layout
.
├── cli.py                  # login/search/product/export commands
├── requirements.txt        # Python dependencies
├── .env.example            # environment variables example
├── src/
│   └── shopee_scraper/
│       ├── __init__.py
│       ├── config.py       # Settings via .env (domain, proxy, headless, limits)
│       ├── session.py      # Contexts; save/load storage_state
│       ├── search.py       # Search, pagination/scroll, card extraction
│       └── utils.py        # Delays, JSON/CSV export, utilities
├── data/
│   └── .gitkeep            # Outputs (gitignored)
└── docs/
    └── ARCHITECTURE_PLAN.md

Patterns and Best Practices
- Retry only on transient errors; stop on login wall/CAPTCHA.
- Fail‑fast on compromised sessions; recycle profile/IP and close Chrome after N pages.
- Quick tests of selectors/endpoint filters on small samples before big runs.
- Align Accept‑Language/locale/timezone/UA; avoid IP changes mid‑session.
- Avoid detectable JS injections; prefer passive observation via CDP.

Summary Roadmap
1) MVP login + search (baseline)
2) Product + schema
3) Resilience (retries/limits + humanization)
4) Profiles + proxies (residential/mobile)
5) CAPTCHA/OTP
6) CDP interception (collect from PDP API)
7) CDP scale (multi‑instance, recycling)
8) Mobile tracks (app API and emulator) in parallel
9) Anti‑detect (optional)
10) DB/exports
11) Observability
12) Continuous maintenance

-------------------------------------------------------------------------------
ADDENDUM (2025‑08) — Current State, Scale Gaps, and Next Steps
-------------------------------------------------------------------------------

Current State — Summary (MVP+ with CDP)
- CDP capture: passive API collection (e.g., /api/v4/pdp/get_pc) in real Chrome via DevTools.
- Profiles & Proxy: `PROFILE_NAME` isolates `.user-data/profiles/<name>`; `PROXY_URL` routed (normalized for `--proxy-server`).
- Consistency: `Accept-Language` and `timezone` aligned to settings; 3P cookies enabled by flag.
- Concurrency: concurrent tabs in PDP batches, with `CDP_MAX_CONCURRENCY` and per‑tab `stagger`.
- Recycling: automatic split by `PAGES_PER_SESSION` when `--launch`, with short randomized cooldown.
- Protections: circuit breaker (CAPTCHA/login/inactivity/403–429), backoff (tenacity), per‑minute rate limit, structured JSONL logs and basic metrics via CLI.
- Local queue: file‑based scheduler (JSON) with `queue add-*`, `queue run`, `queue list`.
- Export: Pydantic normalization, global dedup by `(shop_id,item_id)`; CSV/JSON output.

Scale Gaps (why the current setup doesn’t scale)
- Single machine/IP/profile: one fingerprint/IP concentrates traffic, reduces throughput, and increases detection/blocks.
- Local file queue: does not distribute across processes/hosts; no global per‑profile/IP rate limiting.
- In‑process limiter: adding workers would overflow IP budgets without coordination.
- File outputs: hard to aggregate/deduplicate and serve to consumers with real parallelism.
- Chrome management: static single port (`CDP_PORT`) risks collisions with multiple instances.

Recommended Changes for Scale (what and why)
1) Profile & Proxy Registry
   - What: `profiles.yaml` with `profile_name`, `proxy_url (sticky)`, `locale`, `timezone`, `rps_limit`, `cdp_port_range`.
   - Why: enforce 1 profile ↔ 1 IP with per‑profile limits/params, ensuring geo/locale hygiene and isolation.

2) Distributed Queue + Workers
   - What: replace file scheduler with Redis (RQ/Celery) and add a `worker` command per profile.
   - Why: distribute tasks across processes/hosts; route by domain/region; consistent retries.

3) Global Rate Limiting & Locks
   - What: Redis token buckets per `profile_name` and `proxy_url` and mutual exclusion lock per profile.
   - Why: avoid floods when scaling out; prevent two workers using the same profile simultaneously.

4) Chrome/CDP Management
   - What: `CDP_PORT_RANGE` and free‑port allocator; `user-data-dir` lock; recycling with jitter.
   - Why: run multiple Chromes without port/profile collision; reduce detectable patterns in long sessions.

5) Persistence and Idempotency
   - What: DB (SQLite/Postgres) with upsert by `(shop_id,item_id)` and partitions by date/profile/proxy.
   - Why: cross‑worker deduplication, easy querying/delivery, idempotent reprocessing.

6) Observability
   - What: centralized logs (stdout → collector), per‑profile/proxy metrics (success, duration, bans/hour), simple dashboard.
   - Why: safe operations, detect degradations, prioritize healthier profiles/routes.

7) Security and Hygiene
   - What: secrets outside the repo; never version `storage_state.json`; avoid IP changes mid‑session.
   - Why: protect accounts and reduce operational risk.

8) Packaging & Deploy
   - What: container with stable Chrome and Python deps; `worker` and `queue` entrypoints; process supervision.
   - Why: standardize execution and enable predictable horizontal scale.

How to Achieve (practical steps and impact)
- Short term (low risk)
  1) `profiles.yaml` + loader; validate domain↔locale↔timezone↔proxy coherence.
  2) Port allocator: `CDP_PORT_RANGE` and `user-data-dir` lock.
  3) Containerize (Dockerfile) and parameterize via `.env`/profiles.

- Mid term (enables real scale)
  4) Redis + RQ/Celery: swap local scheduler; add `cli worker --profile X`.
  5) Token bucket + locks (Redis): apply across CDP paths (search/PDP).
  6) Upsert in SQLite/Postgres: exporters also write into the DB.

- Long term (observability/resilience)
  7) Centralized metrics and simple dashboard; alerts on bans/hour.
  8) Mobile/anti‑detect track if CDP degrades.

Acceptance Criteria (examples)
- Two workers on one machine, each with a distinct profile/IP, running 8 tabs each, no port collisions, and no RPS budget violations.
- Re‑running a batch does not duplicate `(shop_id,item_id)` in the DB; exports are idempotent.
- `metrics summary` shows success/latency/blocks by profile/proxy across multiple runs and hosts.
