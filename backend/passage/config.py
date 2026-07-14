from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PASSAGE_", env_file=".env", populate_by_name=True)

    auth_token: str
    database_url: str
    cron_secret: str = Field(alias="CRON_SECRET")


@lru_cache
def get_settings() -> Settings:
    return Settings()
