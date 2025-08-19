# Shopee Scraper — Product Handbook (2025)

This handbook is the single source of truth for product context, goals, roadmap, and operations. It unifies the current architecture, requirements, scaling plan, and future multi‑site direction.

## 1) Vision & Value
- Collect public product/search data safely and reliably, using a real browser (CDP) to minimize anti‑bot detection.
- Operate with account/IP hygiene (one profile per IP), conservative rate limits, and fast stop on block signals.
- Scale horizontally with multiple profiles/proxies, while keeping data quality high (normalized, deduplicated, auditable).

## 2) Current State (Software & Docs)
- Engine: Chrome + CDP capture (passive), concurrent tabs, backoff, circuit breaker, session recycling (pages/session).
- Profiles/Proxy: `PROFILE_NAME` → `.user-data/profiles/<name>`, `PROXY_URL` respected via `--proxy-server`.
- Data: JSONL captures; normalized JSON/CSV exports; global dedup by `(shop_id,item_id)`.
- Orchestration: CLI for login, search, PDP capture, enrich, metrics; simple file‑based queue.
- Safety: CAPTCHA/login/inactivity/403/429 detection; logs JSONL; metrics CLI.
- Docs: Architecture plan, anti‑bot notes, proxies, requirements status, scaling roadmap, multi‑site design.
  - Key docs to read:
    - `docs/ARCHITECTURE_PLAN.txt` (with 2025‑08 addendum)
    - `docs/REQUIREMENTS_STATUS.md` (with scale addendum)
    - `docs/SCALING_ROADMAP.md`
    - `docs/MULTISITE_ADAPTERS.md`

## 3) Product Goals (12 months)
- Reliability: >95% success for PDP captures per healthy profile/proxy in BR domain with conservative limits.
- Scale: Run 10–50 concurrent tabs across 5–10 profiles without tripping limits or collisions.
- Data: Idempotent upserts; consistent dedup and schemas; queryable store (SQLite→Postgres).
- Observability: Per‑profile/proxy success/latency/bans; fast triage when defenses change.
- Extensibility: Add a second site via adapters without touching the core CDP loop.

## 4) Strategy & Scope
- Focus on CDP interception with human‑like navigation; avoid detectable JS injection.
- Expand gradually: profiles registry → distributed queue → global limits/locks → DB persistence → multi‑site adapters.
- Keep ethics and compliance: public data, ToS/robots awareness, no PII, conservative rate limits.

## 5) Operating Model
- One profile per IP (sticky residential/mobile). Avoid mid‑session IP changes.
- Recycle Chrome after N pages with jitter; stagger tab dispatch; backoff on transient failures.
- Stop fast on block signals; mark session degraded; prefer hard circuit in production runs.

## 6) Documentation Map (Unification)
- Product Handbook (this file) — vision, state, goals, roadmap, ops.
- Engineering:
  - Architecture addendum: `docs/ARCHITECTURE_PLAN.txt`
  - Scaling roadmap: `docs/SCALING_ROADMAP.md`
  - Multi‑site design: `docs/MULTISITE_ADAPTERS.md`
  - Requirements & status: `docs/REQUIREMENTS_STATUS.md`
- Ops & How‑to (from README): install, env, CLI commands, metrics; consider splitting to `docs/operations.md` later.

## 7) Backlog Overview (see BACKLOG.md for full details)
- Milestones: M1 Hardening, M2 Scale Infra, M3 Data Store & Obs, M4 Multi‑Site, M5 Mobile/Anti‑detect, M6 Productization.
- Tags: `core`, `cdp`, `infra`, `security`, `observability`, `data`, `multi-site`, `ops`, `docs`.
- Priority scale: P0 (now) to P3 (later). Complexity: S/M/L/XL (relative effort).

## 8) New Requirements (Proposed)
- Profiles registry (`profiles.yaml`) with validation and per‑profile limits.
- CDP port allocator (`CDP_PORT_RANGE`) and profile lock to prevent collisions.
- Distributed queue + global rate limiting (Redis) with token buckets per profile/proxy and locks.
- SQLite→Postgres with upsert and indices; exporters write into DB as well as files.
- Centralized metrics/logs; thresholds for bans/hour; basic dashboard/notebook.
- Site adapter interface and Shopee adapter extraction; `--site` CLI option.

## 9) Risks & Mitigations
- Anti‑bot drift: Multiple tracks (web CDP first; keep an eye on mobile), quick iteration, fixture tests for parsers.
- Proxy instability: Prefer residential/mobile sticky; monitor bans/hour; automatic session recycle.
- Operational complexity: Containerize with Chrome; standardize env; start with a small number of profiles.

## 10) Roadmap Summary
- Short term: profiles registry, port allocator + locks, container base.
- Mid term: distributed queue/workers, global limits/locks, DB upsert path, improved metrics.
- Long term: multi‑site adapters, dashboard, mobile/anti‑detect fallback.

---

For detailed tasks, priorities, and milestones, see `docs/BACKLOG.md`.
