import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("MERIDIAN_DATA", "/data"))
    connector_url: str = os.getenv("CONNECTOR_URL", "http://connector:8092")
    vault_url: str = os.getenv("VAULT_URL", "http://vault:8093")
    model_url: str = os.getenv("MODEL_URL", "http://model:8091/v1")
    model_name: str = os.getenv("MODEL_NAME", "meridian-local")
    model_key: str = os.getenv("MODEL_API_KEY", "local")
    signing_key: str = os.getenv("SIGNING_KEY", "")
    connector_key: str = os.getenv("CONNECTOR_KEY", "")
    cache_seconds: int = 120

    @property
    def database(self) -> Path:
        return self.data_dir / "workspace.sqlite3"


settings = Settings()
