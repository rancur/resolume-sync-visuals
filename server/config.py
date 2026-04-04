"""
Server configuration from environment variables.
"""
import os
from pathlib import Path


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        self.fal_key: str = os.environ.get("FAL_KEY", "")
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
        self.lexicon_host: str = os.environ.get("LEXICON_HOST", "127.0.0.1")
        self.lexicon_port: int = int(os.environ.get("LEXICON_PORT", "48624"))
        self.nas_host: str = os.environ.get("NAS_HOST", "localhost")
        self.nas_ssh_port: int = int(os.environ.get("NAS_SSH_PORT", "7844"))
        self.nas_user: str = os.environ.get("NAS_USER", "admin")
        self.nas_ssh_key: str = os.environ.get(
            "NAS_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519")
        )
        self.resolume_host: str = os.environ.get("RESOLUME_HOST", "127.0.0.1")
        self.resolume_port: int = int(os.environ.get("RESOLUME_PORT", "8080"))
        self.db_path: str = os.environ.get("RSV_DB_PATH", str(Path.home() / ".rsv"))
        self.log_retention_days: int = int(
            os.environ.get("LOG_RETENTION_DAYS", "365")
        )

    @property
    def db_dir(self) -> Path:
        p = Path(self.db_path)
        p.mkdir(parents=True, exist_ok=True)
        return p


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
