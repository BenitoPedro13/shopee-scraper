# Product Backlog — Shopee Scraper (2025)

This backlog defines milestones, epics, tasks, tags, priorities, and complexity estimates. Priorities reflect business value and risk; complexity is relative (S/M/L/XL).

Legend
- Priority: P0 (now), P1 (next), P2 (later), P3 (opportunistic)
- Complexity: S (0.5–1d), M (1–3d), L (3–7d), XL (7d+)
- Tags: `core`, `cdp`, `infra`, `security`, `observability`, `data`, `multi-site`, `ops`, `docs`

## Milestone M1 — Hardening & Hygiene (1–2 weeks)
Goals: Safer runs, tidy docs, clear operator guidance.

- [P0, M, `docs`,`ops`] Unify docs into Product Handbook
  - Deliver `docs/PRODUCT_HANDBOOK.md` with links to architecture, requirements, scaling, multi‑site.
- [P0, S, `security`,`ops`] Clarify safe‑ops defaults
  - Document recommended `REQUESTS_PER_MINUTE`, `PAGES_PER_SESSION`, `CDP_INACTIVITY_S` by profile.
- [P1, M, `cdp`,`core`] Shopee block URL/status list review
  - Verify and extend block patterns; add tests for detection helper.
- [P1, M, `observability`,`ops`] Metrics fields audit
  - Ensure key counters logged: navigate_attempts, responses_matched, circuit trips, duration.

## Milestone M2 — Scale Infrastructure (2–3 weeks)
Goals: Run multiple Chromes safely on one/more hosts; coordinate usage per profile/IP.

- [P0, M, `infra`,`core`] CDP port allocator with range
  - Env `CDP_PORT_RANGE` (e.g., 9300–9400); allocate free port per Chrome instance.
- [P0, M, `infra`,`security`] Profile lockfile
  - Prevent concurrent use of same `user-data-dir` across processes.
- [P1, L, `ops`,`infra`] Container base image
  - Dockerfile with Chrome stable + Python deps; entrypoints for CLI/worker.
- [P1, L, `infra`,`ops`] Profiles registry (spec + loader)
  - `profiles.yaml` with `profile_name`, `proxy_url`, `locale`, `timezone`, `rps_limit`, `cdp_port_range`.

## Milestone M3 — Distributed Queue & Global Limits (3–4 weeks)
Goals: Coordinate work and rate limits across workers/hosts; keep profile/IP hygiene.

- [P0, L, `infra`,`ops`] Replace local queue with Redis RQ (or Celery)
  - `cli worker --profile X`; routing by profile/region; requeue/backoff semantics.
- [P0, L, `infra`,`security`] Token bucket per `profile_name` and `proxy_url`
  - Redis‑based global rate limiter; replace local RateLimiter usage in CDP flows.
- [P1, M, `infra`,`security`] Distributed locks by profile
  - Ensure exclusive use of a profile at any time across the fleet.

## Milestone M4 — Data Store & Idempotency (2–3 weeks)
Goals: Reliable upsert, dedup across workers, and better data access.

- [P0, L, `data`,`core`] SQLite upsert path (upgradeable to Postgres)
  - `db.py` with tables, indices, and upsert by `(shop_id,item_id)`.
- [P1, M, `data`,`core`] Exporters write to DB and files
  - PDP/Search exporters insert/update rows; keep JSON/CSV for audit.
- [P1, M, `observability`,`data`] Run metadata table
  - Track per‑run counters, timings, profile/proxy IDs for reporting.

## Milestone M5 — Observability & SLOs (1–2 weeks)
Goals: Clear view of health; thresholds to act early.

- [P0, M, `observability`,`ops`] Metrics summary enhancement
  - Aggregate by profile/proxy over time windows; export CSV/JSON; sample notebook.
- [P1, M, `observability`,`ops`] Basic thresholds
  - Define acceptable ranges (e.g., bans/hour) and surface warnings in CLI summary.

## Milestone M6 — Multi‑Site Enablement (2–4 weeks)
Goals: Onboard a second site with minimal code churn.

- [P0, L, `multi-site`,`core`] Implement adapter interface and Shopee adapter extraction
  - Introduce `ISiteAdapter`; refactor CDP collector/exporters to call adapter methods.
- [P1, M, `multi-site`,`docs`] Adapter template and docs
  - Provide a skeleton adapter with guidance and tests for new sites.
- [P2, L, `multi-site`,`core`] Add `--site` CLI option and resolver
  - Switch behavior based on site; default remains Shopee.

## Milestone M7 — Mobile & Anti‑detect (exploration) (2–6 weeks)
Goals: Increase resilience if web CDP degrades.

- [P2, XL, `security`,`core`] Mobile app API interception track (research)
  - Identify endpoints, auth, and feasibility; small PoC.
- [P3, XL, `security`,`infra`] Android emulator + ADB capture track (research)
  - System‑level capture of mobile browser/app APIs.
- [P3, L, `security`,`ops`] Anti‑detect browser evaluation (Kameleo, etc.)
  - Small pilot to assess fingerprint stability and overhead.

## Milestone M8 — Productization (ongoing)
Goals: Smooth operations, contributor experience, and compliance.

- [P2, M, `ops`,`docs`] Operations guide & runbooks
  - Runbooks for common failures (captcha spikes, proxy flaps, session degradation).
- [P2, S, `docs`] Issue/PR templates and coding standards
  - Templates, style guide, and minimal contribution rules.
- [P2, S, `security`,`ops`] Secrets management hygiene
  - Ensure creds are env‑only; documented handling for CI/containers.

---

Notes
- Estimates assume a single engineer; parallelization changes timelines.
- Each milestone should ship with: updated docs, minimal tests, and a rollback plan.
