from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEAGUE_MANAGER_", env_file=".env", extra="ignore")

    cors_origin: str = "http://localhost:5190"
    database_url: str = "sqlite:///league_manager.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
