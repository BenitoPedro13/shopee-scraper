from __future__ import annotations

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    # Core
    shopee_domain: str = Field("shopee.com.br", alias="SHOPEE_DOMAIN")
    headless: bool = Field(True, alias="HEADLESS")
    storage_state: str = Field("storage_state.json", alias="STORAGE_STATE")
    user_data_dir: str = Field(".user-data", alias="USER_DATA_DIR")
    data_dir: str = Field("data", alias="DATA_DIR")

    # Locale/Timezone
    locale: str = Field("pt-BR", alias="LOCALE")
    timezone_id: str = Field("America/Sao_Paulo", alias="TIMEZONE")

    # Throttling
    requests_per_minute: int = Field(60, alias="REQUESTS_PER_MINUTE")
    min_delay: float = Field(1.0, alias="MIN_DELAY")
    max_delay: float = Field(2.5, alias="MAX_DELAY")

    # Networking
    proxy_url: str | None = Field(None, alias="PROXY_URL")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()  # Singleton-style settings

