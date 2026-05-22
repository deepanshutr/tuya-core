"""Env-driven configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TUYA_",
        env_file=(".env", str(Path.home() / ".config" / "tuya" / "state.env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bind: str = Field("127.0.0.1:8768", description="uvicorn bind address")
    discover_listen_s: float = Field(
        3.0, description="Seconds to listen on UDP 6666/6667 per discovery pass"
    )
    refresh_interval_s: int = Field(60, description="Per-bulb refresh cadence")
    discover_interval_s: int = Field(600, description="Full re-discover cadence")
    all_concurrency: int = Field(
        16, description="Max concurrent bulbs in a /bulb/all/{op} fan-out"
    )
    log_level: str = Field("INFO", description="Python logging level")
    state_dir: Path = Field(
        default_factory=lambda: Path.home() / ".config" / "tuya",
        description="Where state.json and keys.json live",
    )

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def keys_path(self) -> Path:
        return self.state_dir / "keys.json"


def load() -> Settings:
    return Settings()  # type: ignore[call-arg]
