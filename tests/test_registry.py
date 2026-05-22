"""Bulb registry: target resolution + state.json round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from tuya_core.registry import Registry


@pytest.fixture()
def two_bulb_registry(tmp_path: Path) -> Registry:
    reg = Registry(tmp_path / "state.json")
    reg.upsert_discovered({
        "mac": "aaaaaaaaaaaa", "ip": "192.168.1.10",
        "device_id": "bf01aaa", "protocol_version": "3.3",
    })
    reg.upsert_discovered({
        "mac": "bbbbbbbbbbbb", "ip": "192.168.1.11",
        "device_id": "bf02bbb", "protocol_version": "3.4",
    })
    return reg


def test_resolve_by_mac(two_bulb_registry: Registry) -> None:
    b = two_bulb_registry.resolve("aaaaaaaaaaaa")
    assert b is not None and b.mac == "aaaaaaaaaaaa"
    b = two_bulb_registry.resolve("AA:AA:AA:AA:AA:AA")
    assert b is not None and b.mac == "aaaaaaaaaaaa"


def test_resolve_by_ip(two_bulb_registry: Registry) -> None:
    b = two_bulb_registry.resolve("192.168.1.11")
    assert b is not None and b.mac == "bbbbbbbbbbbb"


def test_resolve_by_name_case_insensitive(two_bulb_registry: Registry) -> None:
    two_bulb_registry.rename("aaaaaaaaaaaa", "Bedroom")
    b = two_bulb_registry.resolve("bedroom")
    assert b is not None and b.mac == "aaaaaaaaaaaa"


def test_resolve_default_picks_earliest_discovered(two_bulb_registry: Registry) -> None:
    b = two_bulb_registry.default()
    assert b is not None and b.mac == "aaaaaaaaaaaa"


def test_resolve_underscore_default_sentinel(two_bulb_registry: Registry) -> None:
    expected = two_bulb_registry.default()
    assert expected is not None
    assert two_bulb_registry.resolve("_default") == expected
    assert two_bulb_registry.resolve("") == expected
    assert two_bulb_registry.resolve(None) == expected


def test_resolve_missing_returns_none(two_bulb_registry: Registry) -> None:
    assert two_bulb_registry.resolve("zz") is None
    assert two_bulb_registry.resolve("192.168.1.99") is None
    assert two_bulb_registry.resolve("nope") is None


def test_upsert_stores_device_id_and_version(two_bulb_registry: Registry) -> None:
    b = two_bulb_registry.resolve("aaaaaaaaaaaa")
    assert b is not None
    assert b.device_id == "bf01aaa"
    assert b.protocol_version == "3.3"


def test_upsert_refreshes_ip_and_version(tmp_path: Path) -> None:
    reg = Registry(tmp_path / "state.json")
    reg.upsert_discovered({
        "mac": "aabbccddeeff", "ip": "192.168.1.5",
        "device_id": "bf09", "protocol_version": "3.3",
    })
    reg.upsert_discovered({
        "mac": "aabbccddeeff", "ip": "192.168.1.6",
        "device_id": "bf09", "protocol_version": "3.4",
    })
    b = reg.resolve("aabbccddeeff")
    assert b is not None
    assert b.last_ip == "192.168.1.6"
    assert b.protocol_version == "3.4"
    assert len(reg.all()) == 1


def test_persistence_roundtrip_mode_0600(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    reg = Registry(p)
    reg.upsert_discovered({
        "mac": "abcdef012345", "ip": "10.0.0.5",
        "device_id": "bf77", "protocol_version": "3.3",
    })
    reg.flush()

    reg2 = Registry(p)
    b = reg2.resolve("abcdef012345")
    assert b is not None
    assert b.last_ip == "10.0.0.5"
    assert b.device_id == "bf77"
    assert (p.stat().st_mode & 0o777) == 0o600


def test_friendly_name_auto_assigned(two_bulb_registry: Registry) -> None:
    names = sorted(b.name for b in two_bulb_registry.all())
    assert names == ["bulb-1", "bulb-2"]


def test_empty_registry_default_is_none(tmp_path: Path) -> None:
    reg = Registry(tmp_path / "state.json")
    assert reg.default() is None
