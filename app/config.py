import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    scans_dir: Path = Path(os.getenv("SCANS_DIR", "/data/scans"))
    appdata_dir: Path = Path(os.getenv("APPDATA_DIR", "/data/appdata"))
    share_secret_env: str = os.getenv("SHARE_SECRET", "")

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

    @property
    def share_secret_path(self) -> Path:
        return self.appdata_dir / "share_secret.key"

    def get_share_secret(self) -> bytes:
        if self.share_secret_env.strip():
            return self.share_secret_env.strip().encode("utf-8")
        try:
            if self.share_secret_path.is_file():
                existing = self.share_secret_path.read_text(encoding="utf-8").strip()
                if existing:
                    return existing.encode("utf-8")
            self.appdata_dir.mkdir(parents=True, exist_ok=True)
            generated = secrets.token_hex(32)
            self.share_secret_path.write_text(generated, encoding="utf-8")
            return generated.encode("utf-8")
        except OSError:
            return b"film-archive-default-hmac-secret-key"

    def ensure_directories(self) -> None:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
