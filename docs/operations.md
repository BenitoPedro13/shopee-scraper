# Operations Guide — Shopee Scraper

This document provides runbooks and day‑2 operations for safe, reliable runs in development and production‑like setups.

## 1) Pre‑Run Checklist
- Environment validate: `python cli.py env-validate` (domain/locale/timezone/proxy/profile)
- Profile hygiene: one `PROFILE_NAME` per account; use `python cli.py profiles list/create/use`
- Proxy hygiene: one sticky residential/mobile IP per profile; avoid mid‑session IP changes
- Timezone/locale: align to target domain region (e.g., BR → pt-BR / America/Sao_Paulo)
- Storage state: for Playwright login runs, keep `storage_state.json` out of VCS; prefer CDP profile login

## 2) Login & Sessions
- Playwright login (baseline): `python cli.py login` (saves `storage_state.json`)
- CDP profile login (preferred for CDP runs): `python cli.py cdp-login`
- Sticky proxy auth prompts: authenticate once via `cdp-login`, then reuse with `--no-launch` to attach
- Recycling policy: keep `PAGES_PER_SESSION` conservative (e.g., 50) to reduce accumulated patterns; cooldown 2–5s

## 3) Running Captures
- PDP (single): `python cli.py cdp-pdp <pdp_url> --timeout 20`
- PDP batch (enrich search export): `python cli.py cdp-enrich-search --launch --per-timeout 8 --stagger 1.0`
- Search capture: `python cli.py cdp-search -k "<keyword>" -p 5 --timeout 12`
- Attach to existing Chrome: add `--no-launch` to reuse an already authenticated instance on `CDP_PORT`

## 4) Circuit Breaker & Tuning
- Signals: captcha/login URLs, 403/429 statuses on filtered endpoints, prolonged inactivity
- Hard vs soft: prefer hard circuit (default). Soft mode for exploration: `--soft-circuit` or `CDP_CIRCUIT_ENABLED=false`
- Inactivity window: adjust with `--circuit-inactivity` or `CDP_INACTIVITY_S` (default 8.0s)
- Concurrency caps: `--concurrency` and `CDP_MAX_CONCURRENCY` (default 12). Stagger tabs with `--stagger` (0.8–1.0s)
- Rate limiting: `REQUESTS_PER_MINUTE` per process/profile. Keep conservative (30–60)

## 5) Data, Logs, and Metrics
- Raw CDP: `data/cdp_pdp_<ts>.jsonl`, `data/cdp_search_<ts>.jsonl`
- Exports: `<...>_export.json` / `<...>_export.csv` (normalized, dedup by `(shop_id,item_id)`)
- Session status: `data/session_status/<PROFILE_NAME>.json` (degraded/healthy flags)
- Events log: `data/logs/events.jsonl` (structured counters and summaries)
- Metrics CLI:
  - Summary: `python cli.py metrics summary [--hours N] [--profile X] [--proxy URL]`
  - Export: `python cli.py metrics export` → `data/metrics/summary.(csv|json)`

## 6) Queue & Scheduling (local mode)
- Add tasks: `python cli.py queue add-search ...`, `python cli.py queue add-enrich ...`
- Inspect queue: `python cli.py queue list`
- Run once: `python cli.py queue run --max-tasks N`
- Note: local file queue is single‑host; for scale, see Scaling Roadmap (Redis + workers)

## 7) Profiles, Proxies, and Ports
- Profiles base: `.user-data/profiles/<PROFILE_NAME>`
- Proxy flag: `PROXY_URL` → Chrome `--proxy-server` (scheme normalized; credentials stripped from flag)
- CDP port: default `CDP_PORT=9222`; for multiple instances per host, set a `CDP_PORT_RANGE` and allocate free ports (see Scaling Roadmap)

## 8) SLOs, Thresholds, and Actions
- Suggestion per healthy profile/IP (BR):
  - PDP success rate ≥ 95%
  - Bans/hour (403/429/captcha) ≤ 3 sustained; if exceeded, stop and recycle profile/IP
  - Average PDP capture duration ≤ 10s under moderate concurrency
- When SLOs are breached:
  - Stop affected runs (hard circuit)
  - Mark session degraded
  - Recycle Chrome (and optionally rotate to a fresh sticky IP)
  - Reduce concurrency and REQUESTS_PER_MINUTE; rerun small sample

## 9) Troubleshooting
- No captures (0 matches):
  - Check `CDP_FILTER_PATTERNS` and adapter filters (future multi‑site); ensure correct domain and login state
  - Increase timeout slightly; verify network events not cached (`Network.setCacheDisabled` is enabled by default)
- Captcha/login loops:
  - Lower RPM and concurrency; ensure locale/timezone alignment; confirm proxy is residential/mobile and geolocated
  - Use `cdp-login` to authenticate once, then attach to the same Chrome
- Proxy auth prompts keep appearing:
  - Prefer provider IP allow‑listing. If not possible, authenticate via `cdp-login` first, then reuse with `--no-launch`
- Port already in use:
  - Adjust `CDP_PORT` or migrate to a `CDP_PORT_RANGE` (and enable port allocator per instance)

## 10) Day‑2 Maintenance
- Data housekeeping: rotate old raw JSONLs and exports to archival storage; keep recent runs hot
- Backups (if DB is enabled later): regular snapshots; verify restore
- Secrets hygiene: proxy creds and tokens only via environment; never commit
- Versioning: avoid breaking CLI; document changes in docs/PRODUCT_HANDBOOK.md and docs/BACKLOG.md
- Health reviews: weekly metrics review per profile/proxy; update limits and profiles as needed

## 11) Capacity Planning
- Start with 3–5 profiles (one sticky IP each); 1–2 Chrome instances per profile; total tabs ≤ 8–12 per host
- Observe bans/hour and latency; scale profiles first, then tabs
- Recycle sessions after `PAGES_PER_SESSION` pages; use random cooldowns to reduce patterns

## 12) References
- Product Handbook: docs/PRODUCT_HANDBOOK.md
- Scaling Roadmap: docs/SCALING_ROADMAP.md
- Backlog: docs/BACKLOG.md
- Multi‑site Design: docs/MULTISITE_ADAPTERS.md
