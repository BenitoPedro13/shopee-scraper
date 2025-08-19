# Shopee Scraper — Requirements & Status (account protection and safe scale)

Last update: 2025‑08‑19 (scaling addendum)

This document tracks the project with top priority on protecting accounts and scaling safely (without sacrificing profile/IP hygiene and session reputation).

---
SCALING ADDENDUM (2025‑08) — Current state, limiters, and how to scale

Current State (summary)
- Stable CDP for PDP and Search with default filters and normalized export (JSON/CSV), dedup by `(shop_id,item_id)`.
- Tab concurrency with recycling by `PAGES_PER_SESSION` and short random cooldown.
- Circuit breaker (captcha/login/inactivity/403–429) + backoff (tenacity) reduce damage and mark session as degraded.
- Local file‑based queue works well on one host; does not coordinate resources across multiple processes/hosts.

Current Limiters (why it doesn’t scale yet)
- Single IP/profile and one host: limited throughput and higher detection risk.
- No global rate limiting and locks: adding workers would blow the IP budget and could share a profile accidentally.
- Single CDP port (fixed): prevents multiple Chrome instances on the same host without collisions.
- File‑only persistence: hinders cross‑worker dedup and real‑time queries/delivery.

Current Priority — Protect Accounts and Scale Safely
- Distribute work across multiple sticky profiles/IPs with per‑profile/per‑proxy limits.
- Eliminate port/profile collisions when running multiple Chromes on the same host.
- Ensure idempotency in reprocessing (upsert by `(shop_id,item_id)`), no duplicates.

New Backlog Items for Scale (complementary to the list below)
- Profiles & proxies registry (`profiles.yaml`) with `profile_name`, `proxy_url`, `locale`, `timezone`, `rps_limit`, `cdp_port_range`.
- CDP port allocator (`CDP_PORT_RANGE`) + lock per `user-data-dir` to prevent profile races.
- Distributed queue (Redis + RQ/Celery) and `worker` command with routing by profile/region.
- Global rate limiting per `profile_name` and `proxy_url` (Redis token bucket) + distributed locks.
- SQLite/Postgres with upsert by `(shop_id,item_id)` and indexes; exporters also write into DB.
- Centralized logs + metrics by profile/proxy (success, duration, bans/hour) and simple dashboard.
- Containerization (stable Chrome + deps) with `worker`/`queue` entrypoints and profile‑based parametrization.

How to Achieve (implementation guide)
1) Profiles & Proxies
   - Create `docs/profiles.example.yaml` and `data/profiles.yaml` (gitignored) with per‑profile parameters.
   - `src/shopee_scraper/profiles.py`: loader + validation; CLI to list/validate.
2) Chrome/CDP
   - `CDP_PORT_RANGE=9300-9400` in `.env`; allocate a free port per worker.
   - Lockfile per `user-data-dir` to prevent concurrent use of the same profile.
3) Packaging
   - Dockerfile with stable Chrome and fonts; entrypoints `cli.py worker`, `cli.py queue`.
4) Queue + Workers
   - Adopt Redis and RQ/Celery; adapt `scheduler.py` keeping local fallback.
   - `cli.py workers start --profiles br_01 br_02` for local spawn.
5) Rate limiting & Locks
   - `limits.py` with Redis token bucket and `with_profile_lock(profile)`; used in all CDP paths.
6) Persistence
   - `db.py` (SQLite first) and exporters also saving into DB (upsert by `(shop_id,item_id)`).

Success Metrics
- 2+ workers per host, 2+ hosts, without violating RPS per profile/IP; no port/profile collisions.
- Reprocessing does not create duplicates in DB; exports consistent.
- `metrics summary/export` reflect distributed executions by profile/proxy.

## Current Priority — Protect Accounts
- One `user-data-dir` per account/session; never reuse across accounts.
- One IP per profile: stable, geolocated residential/mobile proxy. Avoid mid‑session IP changes (sticky session).
- Real browser + CDP: observe traffic (Network.*) without JS injection. Keep 3P cookies, consent, Accept‑Language/timezone coherent.
- Human behavior: home → search/category → PDP; natural dwell/scroll and random timings.
- Conservative limits: ~1–2 req/s; minute budgets and pauses. Stop on block signals.
- Health‑check & circuit breaker: detect login wall/CAPTCHA/empty layout; mark session “degraded” and stop.
- Recycling: restart Chrome/profile after N pages to reduce accumulated patterns.

## Snapshot (Done vs Missing)

### Done
- Headful manual login with persisted session (`storage_state.json`).
- Playwright search (basic scroll), card extraction and JSON/CSV export.
- CDP PDP: capture via `Network.getResponseBody` and normalized export (JSON/CSV).
- CDP Search: listing APIs capture and normalized export (JSON/CSV).
- Enrichment: Search → PDP pipeline (serial and concurrent tabs).
- `.env` config, locale/timezone, 3P cookies flag; directories and gitignore.
- CDP + per‑profile proxy (basic): `--proxy-server` honors `PROXY_URL`.
- Isolated profiles (basic): support for `PROFILE_NAME` → `.user-data/profiles/<PROFILE_NAME>`.
- Minimal health‑check (CDP): if 0 responses captured, mark session as degraded in `data/session_status/<profile>.json` and abort.
- Basic rate limiting (CDP): per‑minute navigation limit.
- Recycling after N pages (CDP): split batches into sessions when `--launch`.
- Headers/timezone coherence (CDP): `Accept-Language` and `timezone` aligned.
- Expanded health‑check + circuit breaker (CDP): CAPTCHA/login/inactivity/403‑429 detection and early abort.
- Backoff with `tenacity` at CDP critical points (navigate/enable/getResponseBody).
- Cooldown between chunks when recycling CDP sessions.
- Structured logs (JSON) + minimal counters in `data/logs/events.jsonl`.
- CDP paginated search (via `page` param + `--all-pages`).
- Profiles CLI (basic): `profiles list/create/use` updating `.env`.
- Environment validation (domain/locale/timezone/proxy/profile) via `env-validate`.
- Circuit/concurrency tuning (CDP): `CDP_INACTIVITY_S`, `CDP_CIRCUIT_ENABLED` (soft circuit), `CDP_MAX_CONCURRENCY`; staggered waits.

### Partial
- Locale/UA/timezone alignment (Playwright ok; CDP partial – review UA and headers).
- Deduplication: now global by `(shop_id,item_id)` in exports (PDP and Search).
- Data modeling: Pydantic schemas applied to PDP/Search.
- Search scroll (CDP): load more items without changing `page` (infinite scroll UX) — optional/pending.
- Concurrency: concurrent tabs implemented; no distributed scheduler/queue; basic structured metrics via CLI.

### Prioritized Backlog (need → less; within each level: lower → higher effort)

Level 1 — Essentials (High need)
- (no items pending in this section)

Level 2 — Important (Medium need)
- CDP Search scrolling (optional): simulate scroll/internal page change to load more items without changing `page`.
- (done) Pydantic Schemas + global dedup `(shop_id,item_id)`.
- Domain↔region/IP mapping (impact: medium, effort: low): validate geo/language/timezone coherence before runs.
- Advanced sticky proxy (impact: medium, effort: medium‑high): extension for auth/allowlist and session tag in username.

Level 3 — Opportunity (Low need)
- DB persistence (impact: medium, effort: medium‑high): SQLite/Postgres with upsert.
- CAPTCHA/OTP providers (impact: medium, effort: high): 2Captcha/Anti‑Captcha and SMS API as fallback.
- Scheduler/queue (impact: high for scale, effort: high): Celery/RQ + per‑profile/IP limits.
- Mobile/anti‑detect (impact: high for resilience, effort: very high): native app/emulator and Kameleo.

## Phase Map (Architecture Plan)
- Phase 1 (MVP): complete.
- Phase 2 (Product/Model): partial — Pydantic schemas and dedup ready; paging by `page` implemented; missing scroll and category coverage.
- Phase 3 (Resilience): progressing — rate limiting, health‑check + circuit breaker, backoff and minimal JSON logs; lacking structured metrics.
- Phase 4 (Profiles/Proxies): partial — isolated profiles by `PROFILE_NAME` and basic `--proxy-server`; missing advanced sticky and richer CLI management.
- Phase 5 (CAPTCHA/OTP): pending — manual only.
- Phase 6/7 (CDP scale/orchestration): partial — tab concurrency and basic recycling; missing distributed scheduler/queue and richer metrics.
- Phases 8–12 (Mobile, Anti‑detect, DB, Observability, Compliance): open (partial compliance via .env/gitignore and conservative limits).

## Detailed Action Items (prioritized)

High Priority (account protection)
— CDP + Proxy per profile
  - Goal: isolate fingerprint and reputation per profile/account with coherent IP.
  - Implementation (low complexity):
    - In `src/shopee_scraper/cdp/collector.py`, include `--proxy-server=<proto>://host:port` in `_build_launch_cmd` when `settings.proxy_url` is set.
    - Credentials in the URL (`http://user:pass@host:port`) or via extension if needed (later).
    - Add per‑profile variables (e.g., `PROFILE_NAME`, `PROFILE_PROXY_URL`) and resolve `user-data-dir` to `.user-data/profiles/<PROFILE_NAME>`.
  - Success signals: correct IP egress (check via an IP echo service), session remains stable between runs.
  - Risks: unstable/datacenter proxies; prefer residential/mobile.

— Isolated profiles
  - Goal: each account has its own Chrome profile (cookies, cache, consent) and IP.
  - Implementation (low complexity):
    - Allow `PROFILE_NAME` in `.env`; build `settings.user_data_dir = .user-data/profiles/<PROFILE_NAME>` if present.
    - Add CLI: `profiles create/list/use` (optional later). First step: just honor `PROFILE_NAME`.
  - Success: separate directories per profile; no session mixing.

— Health‑check & circuit breaker
  - Goal: stop fast on block detection to protect account/IP reputation.
  - Implementation (low‑medium):
    - Reuse `_is_captcha_gate` heuristics (Playwright) and add checks for login/error redirects.
    - Expose `on_block(event, context)` to mark session degraded (e.g., `data/session_degraded/<profile>.flag`) and abort batch.
    - Integrate into CDP: if no expected responses for N seconds or navigation hits `/verify/captcha`, trip breaker and exit.
  - Success: batches stop automatically; logs show cause/next step.

— Rate limiting & backoff
  - Goal: reduce event rate and react to throttling signals.
  - Implementation (low):
    - Create `rate_limiter(tokens_per_minute)` per process/profile.
    - Apply `tenacity` with exponential backoff on 429/5xx.
  - Success: fewer blocks; predictable latency.

— Recycling after N pages
  - Goal: reduce “accumulated patterns” in long sessions.
  - Implementation (low):
    - Page counter in CLI/CDP; after `PAGES_PER_SESSION`, close and relaunch Chrome with same profile/IP (short cooldown).
  - Success: stability in long batches; fewer late‑run blocks.

Medium Priority
- Structured metrics: aggregations/report via CLI (`metrics summary`) and export (`metrics export`); simple notebook in `docs/metrics_example.ipynb`. Dedicated UI pending.
- CDP paging (Search): simulate scroll/internal page change and aggregate multiple responses before export.
- Fingerprint coherence (CDP): align UA/Accept‑Language/timezone and consent; ensure 3P cookies enabled.

Low Priority
- DB (SQLite/Postgres) + upsert.
- CAPTCHA/OTP providers (manual fallback as default).
- Scheduler/queue (basic delivered; future: Celery/RQ and multi‑instance distribution).
- Mobile track and anti‑detect.

## Safe Operation (recommendations)
- One account per browser profile and per IP; never share IP across simultaneous accounts.
- Avoid headless; keep natural dwell/scrolls; don’t run very long batches without recycling instances.
- Monitor block signals; at first signal, stop and recycle profile/IP.
- Do not change IP mid‑session; do not clear cookies between pages in the same session.

## History (summary)
- [x] Headful login and `storage_state.json` (Playwright)
- [x] Search and CSV/JSON export (Playwright)
- [x] CDP PDP: capture and export
- [x] CDP Search: capture and export
- [x] Search→PDP enrichment with concurrent tabs
- [x] `.env` configs; 3P cookies flag; Accept‑Language/timezone (Playwright)
- [x] Per‑profile proxy in CDP (basic)
- [x] Isolated multi‑account profiles (basic via `PROFILE_NAME`)
- [x] Minimal health‑check (marks session degraded if 0 responses)
- [x] Basic rate limiting (per minute)
- [x] Recycling after N pages (CDP, when `--launch`)
- [x] JSON logs + metrics
- [x] Pydantic schemas + global dedup
- [x] CDP search paging via `page`
- [x] Profiles CLI (list/create/use) + env validation
- [x] Basic structured metrics via CLI (summary by profile/proxy)
- [x] Local file queue and simple scheduler via CLI (`queue add-*`, `queue run`, `queue list`)
- [ ] Search scroll via CDP
