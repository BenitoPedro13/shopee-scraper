from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # Core
    shopee_domain: str = Field("shopee.com.br", alias="SHOPEE_DOMAIN")
    headless: bool = Field(True, alias="HEADLESS")
    storage_state: str = Field("storage_state.json", alias="STORAGE_STATE")
    user_data_dir: str = Field(".user-data", alias="USER_DATA_DIR")
    data_dir: str = Field("data", alias="DATA_DIR")

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

    # Networking
    proxy_url: Optional[str] = Field(None, alias="PROXY_URL")

    # Behavior/hardening
    use_persistent_context_for_search: bool = Field(
        True, alias="USE_PERSISTENT_CONTEXT_FOR_SEARCH"
    )
    disable_3pc_phaseout: bool = Field(True, alias="DISABLE_3PC_PHASEOUT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # Singleton-style settings
