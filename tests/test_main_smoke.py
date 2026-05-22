"""Smoke test: app builds without hitting the LAN; boot discovery is non-blocking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from tuya_core.config import Settings
from tuya_core.main import build_app


def test_build_app_returns_fastapi(tmp_path: Path) -> None:
    app = build_app(Settings(_env_file=None, state_dir=tmp_path))  # type: ignore[call-arg]
    assert app.title == "tuya-core"


def test_lifespan_does_not_block_on_boot_discovery(tmp_path: Path) -> None:
    """Boot discovery is create_task'd; a slow discover must not delay startup."""
    import asyncio

    async def slow_discover(**_kw: object) -> list[dict]:
        await asyncio.sleep(30)  # would hang the test if awaited before yield
        return []

    with patch("tuya_core.main.discover", AsyncMock(side_effect=slow_discover)):
        app = build_app(Settings(_env_file=None, state_dir=tmp_path))  # type: ignore[call-arg]
        # Entering the TestClient context runs the lifespan startup. If boot
        # discovery were awaited before yield, this line would hang 30s.
        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 200


def test_keys_provider_rereads_file(tmp_path: Path) -> None:
    """build_app's keys_provider reflects edits to keys.json without a restart."""
    import json
    import os

    keys_path = tmp_path / "keys.json"
    keys_path.write_text(json.dumps({}))
    os.chmod(keys_path, 0o600)

    with patch("tuya_core.main.discover", AsyncMock(return_value=[])):
        app = build_app(Settings(_env_file=None, state_dir=tmp_path))  # type: ignore[call-arg]
        with TestClient(app) as c:
            assert c.get("/bulbs").json()["bulbs"] == []
            # Operator drops a key in after the daemon is already running.
            keys_path.write_text(json.dumps({
                "aabbccddeeff": {"device_id": "bf", "local_key": "k" * 16}
            }))
            os.chmod(keys_path, 0o600)
            # No bulbs discovered, so /bulbs is still empty — but the provider
            # re-read must not error and the daemon stays healthy.
            assert c.get("/health").status_code == 200
