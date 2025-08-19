# Contributing Guide

Thanks for your interest in contributing! This guide explains how to propose changes, open issues, and submit pull requests in sync with the project’s backlog and priorities.

## Ground Rules
- Safety first: do not commit secrets (proxy creds, tokens) or `storage_state.json`.
- Public data only; respect robots.txt and ToS; avoid PII.
- Keep changes focused and minimal; prefer incremental PRs with clear scope.
- Follow the existing code style and structure; update docs when behavior changes.

## Backlog Alignment
- We track milestones, tasks, priorities, and complexity in `docs/BACKLOG.md`.
- When opening an issue or PR, include:
  - Tags: `core`, `cdp`, `infra`, `security`, `observability`, `data`, `multi-site`, `ops`, `docs`
  - Priority: P0 (now), P1 (next), P2 (later), P3 (opportunistic)
  - Complexity: S (0.5–1d), M (1–3d), L (3–7d), XL (7d+)

## Issues
- Use the provided templates (Bug / Feature / Task).
- Be specific: actual vs expected behavior, repro steps, logs, environment.
- For features: link to the relevant milestone/task in `docs/BACKLOG.md` and describe acceptance criteria.

## Pull Requests
- Keep PRs small and cohesive; one theme per PR.
- Include a short description, scope, and before/after notes.
- Reference related issues and backlog items.
- Include test coverage when reasonable (unit or integration); avoid opening browsers in CI.
- Update docs where relevant (README, operations, architecture, handbook/backlog if scope is product‑level).

## Dev Setup
- Python 3.10+
- Create venv and install deps: `pip install -r requirements.txt`
- Install Playwright browser cache in workspace (see README Installation)
- Run tests: `pytest -q`

## Code Areas
- CDP capture logic: `src/shopee_scraper/cdp/`
- CLI commands: `cli.py`
- Settings and validation: `src/shopee_scraper/config.py`, `src/shopee_scraper/envcheck.py`
- Queue and metrics: `src/shopee_scraper/scheduler.py`, `src/shopee_scraper/metrics.py`
- Docs: `docs/` (see `docs/PRODUCT_HANDBOOK.md` and `docs/BACKLOG.md` first)

## Review Process
- We aim for fast, constructive reviews focusing on correctness, safety, and clarity.
- Maintainers may request small refactors or doc updates to keep coherence.
- After approval, squash‑merge unless there’s value in preserving history.

## Contact & Decisions
- Product context and priorities live in: `docs/PRODUCT_HANDBOOK.md` and `docs/BACKLOG.md`.
- Architectural decisions: `docs/ARCHITECTURE_PLAN.md` and design docs (`SCALING_ROADMAP.md`, `MULTISITE_ADAPTERS.md`).
