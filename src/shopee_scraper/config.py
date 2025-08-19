from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    # Core
    shopee_domain: str = Field("shopee.com.br", alias="SHOPEE_DOMAIN")
    headless: bool = Field(True, alias="HEADLESS")
    storage_state: str = Field("storage_state.json", alias="STORAGE_STATE")
    user_data_dir: str = Field(".user-data", alias="USER_DATA_DIR")
    data_dir: str = Field("data", alias="DATA_DIR")

    # Profiles
    profile_name: Optional[str] = Field(None, alias="PROFILE_NAME")

    # Browser
    browser_channel: Optional[str] = Field(None, alias="BROWSER_CHANNEL")
    browser_executable_path: Optional[str] = Field(None, alias="BROWSER_EXECUTABLE_PATH")

    # Locale/Timezone
    locale: str = Field("pt-BR", alias="LOCALE")
    timezone_id: str = Field("America/Sao_Paulo", alias="TIMEZONE")

    # Throttling
    requests_per_minute: int = Field(60, alias="REQUESTS_PER_MINUTE")
    min_delay: float = Field(1.0, alias="MIN_DELAY")
    max_delay: float = Field(2.5, alias="MAX_DELAY")
    pages_per_session: int = Field(50, alias="PAGES_PER_SESSION")

    # Networking
    proxy_url: Optional[str] = Field(None, alias="PROXY_URL")

    # Behavior/hardening
    use_persistent_context_for_search: bool = Field(
        True, alias="USE_PERSISTENT_CONTEXT_FOR_SEARCH"
    )
    disable_3pc_phaseout: bool = Field(True, alias="DISABLE_3PC_PHASEOUT")

    # CDP tuning
    cdp_inactivity_s: float = Field(8.0, alias="CDP_INACTIVITY_S")
    cdp_circuit_enabled: bool = Field(True, alias="CDP_CIRCUIT_ENABLED")
    cdp_max_concurrency: int = Field(12, alias="CDP_MAX_CONCURRENCY")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def model_post_init(self, __context) -> None:  # pydantic v2 hook
        # If PROFILE_NAME is set, resolve user_data_dir to .user-data/profiles/<PROFILE_NAME>
        if self.profile_name:
            base = Path(self.user_data_dir)
            # If user configured a custom base, respect it and append profiles/<name>
            # Default behavior: .user-data/profiles/<name>
            if base.name != "profiles":
                base = base / "profiles"
            self.user_data_dir = str(base / self.profile_name)


settings = Settings()  # Singleton-style settings
