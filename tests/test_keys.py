"""Local-key file loader: ~/.config/tuya/keys.json (mode 0600)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from tuya_core.keys import KeyEntry, load_keys


def _write_keys(path: Path, blob: dict, mode: int = 0o600) -> None:
    path.write_text(json.dumps(blob))
    os.chmod(path, mode)


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    keys = load_keys(tmp_path / "keys.json")
    assert keys == {}


def test_loads_entries_normalising_mac(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, {
        "D8:A0:11:DE:AD:BE": {
            "device_id": "bf01abc1234567890",
            "local_key": "a1b2c3d4e5f6g7h8",
            "version": "3.3",
        }
    })
    keys = load_keys(p)
    assert "d8a011deadbe" in keys
    entry = keys["d8a011deadbe"]
    assert entry == KeyEntry(
        device_id="bf01abc1234567890",
        local_key="a1b2c3d4e5f6g7h8",
        version="3.3",
    )


def test_version_defaults_to_33(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, {
        "aabbccddeeff": {"device_id": "bf09", "local_key": "k" * 16}
    })
    keys = load_keys(p)
    assert keys["aabbccddeeff"].version == "3.3"


def test_entry_missing_required_field_is_skipped(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, {
        "aabbccddeeff": {"device_id": "bf09"},          # no local_key -> skip
        "112233445566": {"device_id": "bf10", "local_key": "k" * 16},
    })
    keys = load_keys(p)
    assert "aabbccddeeff" not in keys
    assert "112233445566" in keys


def test_corrupt_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    p.write_text("{not json")
    os.chmod(p, 0o600)
    assert load_keys(p) == {}


def test_loose_mode_warns_but_still_loads(
    tmp_path: Path, caplog: logging.LogCaptureFixture
) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, {"aabbccddeeff": {"device_id": "bf", "local_key": "k" * 16}}, mode=0o644)
    with caplog.at_level(logging.WARNING, logger="tuya_core.keys"):
        keys = load_keys(p)
    assert "aabbccddeeff" in keys
    assert any("0600" in r.message for r in caplog.records)


def test_local_key_never_logged(
    tmp_path: Path, caplog: logging.LogCaptureFixture
) -> None:
    """No log line at any level may contain the raw local_key."""
    secret = "SUPERSECRETKEY16"
    p = tmp_path / "keys.json"
    _write_keys(p, {"aabbccddeeff": {"device_id": "bf", "local_key": secret}}, mode=0o644)
    with caplog.at_level(logging.DEBUG, logger="tuya_core.keys"):
        load_keys(p)
    assert all(secret not in r.getMessage() for r in caplog.records)
