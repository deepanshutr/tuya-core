"""/bulb/all/{op} broadcast family — amendment §A2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tuya_core.api import create_app
from tuya_core.driver import TuyaError
from tuya_core.keys import KeyEntry
from tuya_core.registry import Registry

_MAC_A = "d8a011000aaa"
_MAC_B = "d8a011000bbb"
_MAC_C = "d8a011000ccc"  # deliberately key-missing


def _key() -> KeyEntry:
    return KeyEntry(device_id="bf", local_key="k" * 16, version="3.3")


class RecordingDriver:
    def __init__(self) -> None:
        self.on_calls: list[str] = []

    async def get_state(self, ip: str, key: KeyEntry) -> dict:
        return {}

    async def turn_on(self, ip: str, key: KeyEntry) -> dict:
        self.on_calls.append(ip)
        return {"ok": True}

    async def turn_off(self, ip: str, key: KeyEntry) -> dict:
        return {"ok": True}

    async def set_brightness(self, ip: str, key: KeyEntry, *, level: int) -> dict:
        return {"ok": True}

    async def set_temp(self, ip: str, key: KeyEntry, *, kelvin: int) -> dict:
        return {"ok": True}

    async def set_color(self, ip: str, key: KeyEntry, *, r: int, g: int, b: int) -> dict:
        return {"ok": True}

    async def set_scene(self, ip: str, key: KeyEntry, *, dpid: int, value: Any) -> dict:
        return {"ok": True}


async def _noop_discover() -> int:
    return 0


def _make_client(
    *, driver: Any, macs: list[str], keyed: set[str], concurrency: int = 16
) -> tuple[TestClient, Registry]:
    """Build an app whose registry holds `macs` and whose keys cover `keyed`."""
    import tempfile

    reg = Registry(Path(tempfile.mkdtemp()) / "state.json")
    for i, mac in enumerate(macs):
        reg.upsert_discovered({
            "mac": mac, "ip": f"192.168.1.{10 + i}",
            "device_id": f"bf{i}", "protocol_version": "3.3",
        })
    keys = {m: _key() for m in keyed}
    app = create_app(
        registry=reg,
        driver=driver,
        run_discovery=_noop_discover,
        keys_provider=lambda: keys,
        all_concurrency=concurrency,
    )
    return TestClient(app), reg


def test_all_on_flips_every_keyed_bulb() -> None:
    driver = RecordingDriver()
    c, _ = _make_client(driver=driver, macs=[_MAC_A, _MAC_B], keyed={_MAC_A, _MAC_B})
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    body = r.json()
    assert body["op"] == "on"
    assert body["total"] == 2
    assert body["ok"] == 2
    assert body["failed"] == 0
    assert len(body["results"]) == 2
    assert all(entry["ok"] for entry in body["results"])
    assert sorted(driver.on_calls) == ["192.168.1.10", "192.168.1.11"]
    assert "duration_ms" in body


def test_all_off_returns_200() -> None:
    c, _ = _make_client(driver=RecordingDriver(), macs=[_MAC_A], keyed={_MAC_A})
    r = c.post("/bulb/all/off")
    assert r.status_code == 200
    assert r.json()["op"] == "off"


def test_all_brightness_validates_body() -> None:
    c, _ = _make_client(driver=RecordingDriver(), macs=[_MAC_A], keyed={_MAC_A})
    assert c.post("/bulb/all/brightness", json={"level": 999}).status_code == 422
    r = c.post("/bulb/all/brightness", json={"level": 40})
    assert r.status_code == 200
    assert r.json()["op"] == "brightness"


def test_all_temp_and_color_and_scene() -> None:
    c, _ = _make_client(driver=RecordingDriver(), macs=[_MAC_A], keyed={_MAC_A})
    assert c.post("/bulb/all/temp", json={"kelvin": 4000}).json()["op"] == "temp"
    assert c.post("/bulb/all/color", json={"r": 1, "g": 2, "b": 3}).json()["op"] == "color"
    assert c.post("/bulb/all/scene", json={"scene": "white"}).json()["op"] == "scene"


def test_all_scene_unknown_returns_400() -> None:
    """Bad scene name fails fast at 400 before any fan-out."""
    c, _ = _make_client(driver=RecordingDriver(), macs=[_MAC_A], keyed={_MAC_A})
    assert c.post("/bulb/all/scene", json={"scene": "nonsense"}).status_code == 400


def test_all_on_empty_registry_returns_zeroes() -> None:
    c, _ = _make_client(driver=RecordingDriver(), macs=[], keyed=set())
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "op": "on", "total": 0, "ok": 0, "failed": 0,
        "duration_ms": body["duration_ms"], "results": [],
    }


def test_all_on_key_missing_bulb_recorded_as_failed() -> None:
    """A key-missing bulb is NOT silently skipped; it lands in results as failed."""
    c, _ = _make_client(
        driver=RecordingDriver(), macs=[_MAC_A, _MAC_C], keyed={_MAC_A}
    )
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["ok"] == 1
    assert body["failed"] == 1
    failed = next(e for e in body["results"] if not e["ok"])
    assert failed["mac"] == _MAC_C
    assert failed["error"] == "key_missing"


def test_all_on_single_bulb_timeout_recorded() -> None:
    """A TuyaError on one bulb is caught; the op still returns 200."""

    class OneFails(RecordingDriver):
        async def turn_on(self, ip: str, key: KeyEntry) -> dict:
            if ip == "192.168.1.11":
                raise TuyaError("udp_timeout")
            return {"ok": True}

    c, _ = _make_client(driver=OneFails(), macs=[_MAC_A, _MAC_B], keyed={_MAC_A, _MAC_B})
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] == 1
    assert body["failed"] == 1
    failed = next(e for e in body["results"] if not e["ok"])
    assert "udp_timeout" in failed["error"]


def test_all_on_every_bulb_fails_still_200() -> None:
    class AllFail(RecordingDriver):
        async def turn_on(self, ip: str, key: KeyEntry) -> dict:
            raise TuyaError("network down")

    c, _ = _make_client(driver=AllFail(), macs=[_MAC_A, _MAC_B], keyed={_MAC_A, _MAC_B})
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] == 0
    assert body["failed"] == 2


def test_all_on_unexpected_exception_does_not_escape() -> None:
    """A non-TuyaError exception from a bulb is caught and surfaced, not 500."""

    class Explodes(RecordingDriver):
        async def turn_on(self, ip: str, key: KeyEntry) -> dict:
            raise RuntimeError("kaboom")

    c, _ = _make_client(driver=Explodes(), macs=[_MAC_A], keyed={_MAC_A})
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    body = r.json()
    assert body["failed"] == 1
    assert "kaboom" in body["results"][0]["error"]


def test_all_respects_concurrency_cap() -> None:
    """With cap=2 and 5 bulbs, no more than 2 driver calls run simultaneously."""
    import asyncio

    peak = 0
    current = 0
    lock = asyncio.Lock()

    class Counting(RecordingDriver):
        async def turn_on(self, ip: str, key: KeyEntry) -> dict:
            nonlocal peak, current
            async with lock:
                current += 1
                peak = max(peak, current)
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1
            return {"ok": True}

    macs = [f"d8a01100{i:04x}" for i in range(5)]
    c, _ = _make_client(
        driver=Counting(), macs=macs, keyed=set(macs), concurrency=2
    )
    r = c.post("/bulb/all/on")
    assert r.status_code == 200
    assert r.json()["ok"] == 5
    assert peak <= 2
