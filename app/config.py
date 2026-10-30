import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    scans_dir: Path = Path(os.getenv("SCANS_DIR", "/data/scans"))
    appdata_dir: Path = Path(os.getenv("APPDATA_DIR", "/data/appdata"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def db_dir(self) -> Path:
        return self.appdata_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "archive.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def cache_dir(self) -> Path:
        return self.appdata_dir / "cache"

    @property
    def covers_dir(self) -> Path:
        return self.cache_dir / "covers"

    @property
    def thumbs_dir(self) -> Path:
        return self.cache_dir / "thumbs"

    def ensure_directories(self) -> None:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
