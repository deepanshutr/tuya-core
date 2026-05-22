"""Settings parse env-prefixed vars with sane defaults."""

from __future__ import annotations

import os

import pytest

from tuya_core.config import Settings


def test_defaults_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in list(os.environ):
        if k.startswith("TUYA_"):
            monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.bind == "127.0.0.1:8768"
    assert s.discover_listen_s == 3.0
    assert s.refresh_interval_s == 60
    assert s.discover_interval_s == 600
    assert s.all_concurrency == 16
    assert s.log_level == "INFO"
    assert str(s.state_dir).endswith("tuya")
    assert str(s.state_path).endswith("state.json")
    assert str(s.keys_path).endswith("keys.json")


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUYA_BIND", "127.0.0.1:9100")
    monkeypatch.setenv("TUYA_REFRESH_INTERVAL_S", "30")
    monkeypatch.setenv("TUYA_ALL_CONCURRENCY", "8")
    s = Settings(_env_file=None)
    assert s.bind == "127.0.0.1:9100"
    assert s.refresh_interval_s == 30
    assert s.all_concurrency == 8
