from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str
    public_base_url: str | None = None
    host: str = "0.0.0.0"
    port: int = 8080
    # Каталог со сборкой Web App (Vite → webapp/dist). Раздаётся под /app,
    # если каталог существует; иначе бэкенд поднимается без Mini App
    # (dev, CI без node). См. app._mount_webapp.
    webapp_dist_dir: str = "webapp/dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
