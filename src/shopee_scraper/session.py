"""Session and browser context helpers (to be implemented).

Next steps:
- Implement login flow in headful mode and save storage_state.json
- Create contexts with saved storage_state for authenticated scraping
"""

from __future__ import annotations

from pathlib import Path

from .config import settings


def storage_state_path() -> Path:
    return Path(settings.storage_state)


def ensure_data_dirs() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.user_data_dir).mkdir(parents=True, exist_ok=True)


# Placeholders to be implemented in the coding phase
async def login_and_save_session() -> None:
    """Open a headful browser, let the user login, then save storage state."""
    raise NotImplementedError


async def create_authenticated_context():
    """Create a Playwright browser context using the persisted storage state."""
    raise NotImplementedError

