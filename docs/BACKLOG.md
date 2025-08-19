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

## Milestone M9 — SDK MVP (2–4 weeks)
Goals: Deliver a developer-friendly library so users plug site logic without handling anti-bot and orchestration details.

- [P0, L, `core`,`multi-site`,`docs`] Extract core engine and site adapter seam
  - Move reusable CDP logic to `src/core`; implement `ISiteAdapter` and extract Shopee adapter; update docs/MULTISITE_ADAPTERS.md if needed.
- [P0, M, `core`,`docs`] Public Python API and quickstarts
  - `Client(site, profile, proxy)` with `search()` and `enrich_pdp()`; write two quickstarts and docstrings.
- [P1, M, `infra`,`ops`] PyPI packaging and versioning
  - Build and publish package (name TBD); semantic versioning; basic changelog.
- [P1, M, `observability`,`docs`] Error model and messages
  - Standardize exceptions (e.g., BlockDetected, ProxyAuthRequired); document troubleshooting.
- [P1, M, `core`,`security`] Safe defaults for limits
  - Set conservative RPM/timeouts/concurrency per adapter; expose overrides.

Acceptance Criteria
- Installing the package and running two copy-paste examples works without code changes beyond env setup.
- Shopee behavior via SDK matches current CLI outputs (same normalized CSV/JSON) for a sample run.
- Clear errors for common failures (captcha/login, proxy auth, port in use) with documented fixes.

## Milestone M10 — SaaS Beta (4–8 weeks)
Goals: Managed execution with simple HTTP API, keys, and a basic dashboard to retrieve outputs.

- [P0, L, `infra`,`ops`] Worker container with Chrome and launcher
  - Docker image, health checks, environment-driven config; CDP port allocator and profile locks.
- [P0, L, `infra`,`ops`] Redis queue + API service (REST)
  - Endpoints: `POST /v1/jobs/search`, `POST /v1/jobs/pdp`, `GET /v1/jobs/{id}`; enqueue, track, and return links.
- [P1, L, `data`,`ops`] Storage for outputs and metadata
  - Store raw JSONL (object storage) and normalized CSV/JSON; job/run table with counters and timings.
- [P1, M, `security`,`ops`] API keys and basic quotas
  - Key issuance, per-key/min quotas and RPM caps; request validation.
- [P2, M, `observability`,`ops`] Minimal dashboard
  - List jobs, status, success rate, bans/hour, and download links for recent runs.

Acceptance Criteria
- Creating a job via REST returns a job id and, when done, accessible links to outputs (JSONL + CSV/JSON).
- Quotas enforced per API key; jobs fail gracefully on block signals with clear status.
- Two workers on one host process multiple jobs concurrently without port/profile collisions.
