# Multi‑Site Architecture — Design Doc (2025)

This document proposes how to evolve the current Shopee‑focused scraper into a cleanly extensible, multi‑site framework while preserving the anti‑bot hygiene, safety controls, and CDP capture strengths already in place. It aims to be explicit about what we have today, what is site‑agnostic, what must become pluggable, and how to migrate with minimal disruption.

## Purpose & Scope
- Purpose: Enable onboarding of new e‑commerce (or content) sites with minimal code changes by introducing a site adapter layer that defines endpoints, health signals, normalization, and limits per site.
- Out of scope: Implementing the adapters themselves for other sites; replacing CDP with native SDKs; deep mobile/emulator track. These are future phases.

## Current State (What’s Reusable vs Shopee‑Specific)

Reusable (site‑agnostic) infrastructure:
- Real Chrome + CDP: launch/attach, enable Network domain, capture responses, backoff, JSONL outputs.
- Safety: circuit breaker (captcha/login/inactivity/403/429), retries, staggered concurrency, per‑minute rate limit, session recycling with jitter.
- Session hygiene: persistent Chrome profiles, proxy routing, locale/timezone alignment, 3P cookie flag.
- Orchestration & UX: CLI commands, local queue, batched PDP capture (serial or concurrent tabs), metrics/logging/export pipeline.

Shopee‑specific parts:
- Endpoint filter patterns (e.g., `/api/v4/pdp/get_pc`, Search endpoints) and block URL patterns (captcha/login).
- Normalization schemas for PDP/Search and dedup keys `(shop_id,item_id)`.
- URL building/pagination for Search and PDP flows (query params, paging behavior).
- Region mappings tuned to `shopee.com.br`.

Conclusion: The “engine” is reusable; we need a clean adapter seam for: filters, health signals, URL builders, normalization, limits.

## Design Goals
- Pluggable: Add a site by implementing a small, well‑typed interface.
- Explicit: Make site‑specific decisions (filters/health/limits) declarative and visible in code/config.
- Safe by default: Keep existing circuit breaker/rate limits/recycling in effect per site.
- Minimal migration: Move Shopee specifics into `sites/shopee` without large code churn.
- Testable: Site logic testable with fixtures (JSON bodies, URL builders) without running Chrome.

Non‑Goals
- Unifying all sites under a universal schema; each site can define its own normalized models initially.
- Solving app/mobile tracks right away; this remains a parallel strategy.

## High‑Level Architecture

Proposed layout:
```
src/
  core/
    cdp/                 # generic CDP helpers (launch, capture loop)
    limits.py            # rate limits (local; later: Redis)
    logs.py, metrics.py  # logging & metrics infra
    queue/               # local or distributed scheduler facades
  sites/
    shopee/
      adapter.py         # implements ISiteAdapter for Shopee
      schemas.py         # Pydantic models for PDP/Search
    <newsite>/
      adapter.py
      schemas.py
  shopee_scraper/        # compatibility layer (current package)
    (gradually delegates to core + current default site)
```

Configuration:
- Global `SITE` (env/CLI) selects adapter.
- Profiles registry (future) carries `site`, `profile_name`, `proxy_url`, `locale`, `timezone`, `limits`.

## Site Adapter Interface

Python sketch (documentational, not binding):
```python
from typing import Iterable, List, Dict, Optional, Protocol

class SiteLimits(Protocol):
    rps_limit: int
    pages_per_session: int
    max_concurrency: int
    inactivity_s: float

class ISiteAdapter(Protocol):
    # Identity
    name: str  # "shopee"
    domain: str  # "shopee.com.br"

    # Filters for CDP capture
    def filter_patterns_pdp(self) -> Iterable[str]: ...
    def filter_patterns_search(self) -> Iterable[str]: ...

    # Health signals (URLs/status codes)
    def is_block_url(self, url: str) -> bool: ...  # e.g., captcha/login/verification pages
    def is_block_status(self, status: int) -> bool: ...  # e.g., 403/429 family

    # URL builders
    def search_url(self, keyword: str, page: int = 0) -> str: ...
    # Optionally: category_url(), shop_url(), pdp_url(item_id,...)

    # Normalization (parsers for captured bodies)
    def parse_pdp(self, body: str) -> Optional[Dict]: ...
    def parse_search(self, body: str) -> List[Dict]: ...
    def dedup_key(self, row: Dict) -> Optional[str]: ...  # e.g., f"{shop_id}:{item_id}"

    # Limits & behavior
    def default_limits(self) -> SiteLimits: ...

```

Adapter responsibilities:
- Provide endpoint filters (regex list) to CDP engine.
- Expose health detection tailored to the site’s block pages and statuses.
- Build navigation URLs, including paging strategy or scroll‑like paging if needed.
- Convert raw API bodies into normalized rows, including robust dedup keys.
- Provide sane default limits (RPS, concurrency, inactivity) per site.

## Integration Points (Where to Plug In)
- CDP Collector: Replace hardcoded `default_patterns` and block URL checks by calls to the adapter. Allow env override via `CDP_FILTER_PATTERNS` as today.
- Exporters: Call adapter parsers for PDP/Search normalization; write rows and dedup using adapter’s key.
- CLI: Add `--site` option and/or `SITE` in `.env`; default to Shopee adapter for backward compatibility.
- Config/Profiles: When using `profiles.yaml`, each profile maps to a `site` and carries locale/timezone/limits overrides.
- Circuit breaker & limits: Use adapter’s defaults for `inactivity_s`, `max_concurrency`, `pages_per_session` unless explicitly overridden.

## Migration Plan (Minimal Churn)
1) Create `src/sites/shopee/adapter.py` implementing `ISiteAdapter` using current constants:
   - Move filter patterns for PDP/Search and block‑URL regexes from `cdp/collector.py`.
   - Move dedup key `(shop_id,item_id)` and parsing from existing exporters/schemas.
   - Provide `search_url()` compatible with current behavior.
2) Introduce a thin `get_adapter(site_name)` resolver. Default to `shopee` when unset.
3) Update CDP collector and exporters to use adapter methods instead of hardcoded values (keep env overrides).
4) Add `--site` to relevant CLI commands (default remains Shopee) and pass through to adapter resolver.
5) Tests: Fixture bodies for PDP/Search parsed by adapter; golden tests for URL builders and health detection.

Backward compatibility: existing commands and `.env` continue working for Shopee without requiring `--site`.

## Example Adapter Outline (Shopee)

```python
# src/sites/shopee/adapter.py (outline)
import re
from typing import Iterable, List, Dict, Optional

class Limits:
    rps_limit = 60
    pages_per_session = 50
    max_concurrency = 12
    inactivity_s = 8.0

class ShopeeAdapter:
    name = "shopee"
    domain = "shopee.com.br"

    def filter_patterns_pdp(self) -> Iterable[str]:
        return [r"/api/v4/pdp/get_pc"]

    def filter_patterns_search(self) -> Iterable[str]:
        return [r"/api/v4/search/", r"/api/v2/search_items", r"/api/v4/recommend/"]

    def is_block_url(self, url: str) -> bool:
        return any(re.search(p, url) for p in [
            r"/verify/captcha", r"/portal/verification", r"/account/login", r"captcha", r"/user/login",
        ])

    def is_block_status(self, status: int) -> bool:
        return status in (403, 429)

    def search_url(self, keyword: str, page: int = 0) -> str:
        import urllib.parse as _u
        return f"https://{self.domain}/search?keyword={_u.quote_plus(keyword)}&page={page}"

    def parse_pdp(self, body: str) -> Optional[Dict]:
        # Delegate to existing schemas to avoid duplication
        # return ShopeePDPSchema.model_validate_json(body).model_dump()
        return None

    def parse_search(self, body: str) -> List[Dict]:
        return []

    def dedup_key(self, row: Dict) -> Optional[str]:
        sid, iid = row.get("shop_id"), row.get("item_id")
        return f"{sid}:{iid}" if sid is not None and iid is not None else None

    def default_limits(self):
        return Limits()
```

## Testing Strategy
- Unit tests (no Chrome):
  - URL builders: keywords → URL with expected paging semantics.
  - Health signals: block URLs/status recognition.
  - Parsers: fixture JSON bodies → normalized rows + dedup keys (golden files).
- Integration (with Chrome):
  - Smoke test for `cdp-search` and `cdp-pdp` ensuring at least one match under tolerant settings (soft circuit).
- Non‑flaky execution: keep Chrome tests optional; run unit tests by default.

## Operational Considerations (Multi‑Site)
- Profiles & Proxies: one profile/IP per site/region; avoid sharing IPs across different sites concurrently.
- Limits per site: stricter or looser depending on defenses; adapter provides defaults, profiles can override.
- Locale/Timezone: align to site/region domain; validate before runs.
- Consent & 3P cookies: some sites rely on third‑party widgets; keep flags that avoid phase‑out breaking flows.

## Risks & Mitigations
- Anti‑bot variability: endpoints and block signals differ; codify health detection in adapter and keep circuit breaker hard by default.
- Dynamic headers/tokens: CDP helps by executing the site’s JS in a real browser; body/headers availability may vary.
- Schema drift: changes in APIs break parsers; version schemas and keep fixture tests.
- Complexity growth: isolate complexity within each adapter and keep core minimal.

## Roadmap (Adapter Workstream)
1) Extract Shopee adapter and adapter resolver; wire CDP collector and exporters to use it.
2) Add `--site` to CLI commands; default to Shopee to avoid breaking changes.
3) Build unit tests for adapter surface; add fixture samples.
4) Prepare a “template adapter” with stubs and docs for onboarding new sites.
5) (Optional) Profiles registry gains `site` field and per‑site limits.

## Acceptance Criteria
- Running existing Shopee commands uses the Shopee adapter transparently; behavior unchanged.
- Switching `--site <name>` swaps filter patterns, block detection, URL builders, and normalization without touching the core capture loop.
- Unit tests cover adapter functions (URL builders, health, parsers, dedup key) with fixtures.

## Open Questions
- Should normalization converge to a shared product schema across sites, or remain per‑site with aggregation later?
- How to version adapters and schemas as sites evolve (semver per adapter package)?
- What’s the minimum viable test data set we can maintain to detect breaking changes early?

