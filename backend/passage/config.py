from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PASSAGE_", env_file=".env")

    auth_token: str
    database_path: Path = Path("./data/passage.db")
    static_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
