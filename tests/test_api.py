"""FastAPI route tests using TestClient + a stub TuyaDriver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tuya_core.api import create_app
from tuya_core.driver import TuyaError
from tuya_core.keys import KeyEntry
from tuya_core.registry import Registry


class StubDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.state: dict[str, Any] = {"dps": {"20": True, "22": 80}}

    async def get_state(self, ip: str, key: KeyEntry) -> dict:
        self.calls.append(("get_state", ip, {}))
        return self.state

    async def turn_on(self, ip: str, key: KeyEntry) -> dict:
        self.calls.append(("turn_on", ip, {}))
        return {"ok": True}

    async def turn_off(self, ip: str, key: KeyEntry) -> dict:
        self.calls.append(("turn_off", ip, {}))
        return {"ok": True}

    async def set_brightness(self, ip: str, key: KeyEntry, *, level: int) -> dict:
        self.calls.append(("set_brightness", ip, {"level": level}))
        return {"ok": True}

    async def set_temp(self, ip: str, key: KeyEntry, *, kelvin: int) -> dict:
        self.calls.append(("set_temp", ip, {"kelvin": kelvin}))
        return {"ok": True}

    async def set_color(self, ip: str, key: KeyEntry, *, r: int, g: int, b: int) -> dict:
        self.calls.append(("set_color", ip, {"r": r, "g": g, "b": b}))
        return {"ok": True}

    async def set_scene(self, ip: str, key: KeyEntry, *, dpid: int, value: Any) -> dict:
        self.calls.append(("set_scene", ip, {"dpid": dpid, "value": value}))
        return {"ok": True}


_KEYED_MAC = "d8a011deadbe"
_UNKEYED_MAC = "d8a011000000"


def _key() -> KeyEntry:
    return KeyEntry(device_id="bf01abc", local_key="a1b2c3d4e5f6g7h8", version="3.3")


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, Registry, StubDriver]:
    reg = Registry(tmp_path / "state.json")
    reg.upsert_discovered({
        "mac": _KEYED_MAC, "ip": "192.168.1.7",
        "device_id": "bf01abc", "protocol_version": "3.3",
    })
    reg.upsert_discovered({
        "mac": _UNKEYED_MAC, "ip": "192.168.1.8",
        "device_id": "bf02xyz", "protocol_version": "3.4",
    })
    driver = StubDriver()
    keys = {_KEYED_MAC: _key()}  # _UNKEYED_MAC deliberately absent

    async def fake_discover() -> int:
        return 0

    app = create_app(
        registry=reg,
        driver=driver,
        run_discovery=fake_discover,
        keys_provider=lambda: keys,
        all_concurrency=16,
    )
    return TestClient(app), reg, driver


def test_health(client) -> None:
    c, *_ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_list_bulbs_includes_protocol_tuya(client) -> None:
    c, *_ = client
    r = c.get("/bulbs")
    assert r.status_code == 200
    bulbs = r.json()["bulbs"]
    assert len(bulbs) == 2
    assert all(b["protocol"] == "tuya" for b in bulbs)


def test_list_marks_keyed_bulb_key_present(client) -> None:
    c, *_ = client
    bulbs = c.get("/bulbs").json()["bulbs"]
    keyed = next(b for b in bulbs if b["mac"] == _KEYED_MAC)
    assert keyed["key_missing"] is False


def test_list_marks_unkeyed_bulb_key_missing(client) -> None:
    c, *_ = client
    bulbs = c.get("/bulbs").json()["bulbs"]
    unkeyed = next(b for b in bulbs if b["mac"] == _UNKEYED_MAC)
    assert unkeyed["key_missing"] is True


def test_list_never_leaks_local_key(client) -> None:
    """The /bulbs payload must not contain any local_key material."""
    c, *_ = client
    body = c.get("/bulbs").text
    assert "a1b2c3d4e5f6g7h8" not in body
    assert "local_key" not in body


def test_get_bulb_by_mac(client) -> None:
    c, _, driver = client
    r = c.get(f"/bulb/{_KEYED_MAC}")
    assert r.status_code == 200
    assert r.json()["protocol"] == "tuya"
    assert driver.calls[0] == ("get_state", "192.168.1.7", {})


def test_get_bulb_404(client) -> None:
    c, *_ = client
    assert c.get("/bulb/notathing").status_code == 404


def test_get_bulb_unkeyed_returns_412(client) -> None:
    """Reading state of a key-missing bulb is a precondition failure too."""
    c, *_ = client
    r = c.get(f"/bulb/{_UNKEYED_MAC}")
    assert r.status_code == 412
    assert _UNKEYED_MAC in r.json()["detail"]["error"]


def test_bulbs_default_returns_earliest(client) -> None:
    c, *_ = client
    r = c.get("/bulbs/default")
    assert r.status_code == 200
    assert r.json()["mac"] == _KEYED_MAC


def test_on_off(client) -> None:
    c, _, driver = client
    assert c.post(f"/bulb/{_KEYED_MAC}/on").status_code == 200
    assert driver.calls[-1] == ("turn_on", "192.168.1.7", {})
    assert c.post(f"/bulb/{_KEYED_MAC}/off").status_code == 200
    assert driver.calls[-1] == ("turn_off", "192.168.1.7", {})


def test_brightness_validation(client) -> None:
    c, *_ = client
    assert c.post(f"/bulb/{_KEYED_MAC}/brightness", json={"level": 999}).status_code == 422
    assert c.post(f"/bulb/{_KEYED_MAC}/brightness", json={"level": 50}).status_code == 200


def test_temp_validation(client) -> None:
    c, *_ = client
    assert c.post(f"/bulb/{_KEYED_MAC}/temp", json={"kelvin": 1000}).status_code == 422
    assert c.post(f"/bulb/{_KEYED_MAC}/temp", json={"kelvin": 4000}).status_code == 200


def test_color(client) -> None:
    c, _, driver = client
    r = c.post(f"/bulb/{_KEYED_MAC}/color", json={"r": 255, "g": 0, "b": 100})
    assert r.status_code == 200
    assert driver.calls[-1][2] == {"r": 255, "g": 0, "b": 100}


def test_scene_by_name(client) -> None:
    c, _, driver = client
    r = c.post(f"/bulb/{_KEYED_MAC}/scene", json={"scene": "white"})
    assert r.status_code == 200
    assert driver.calls[-1][2] == {"dpid": 21, "value": "white"}


def test_scene_unknown_returns_400(client) -> None:
    c, *_ = client
    r = c.post(f"/bulb/{_KEYED_MAC}/scene", json={"scene": "no-such-scene"})
    assert r.status_code == 400


def test_rename(client) -> None:
    c, reg, _ = client
    r = c.post(f"/bulb/{_KEYED_MAC}/name", json={"name": "kitchen"})
    assert r.status_code == 200
    assert reg.resolve("kitchen") is not None


def test_control_unkeyed_bulb_returns_412(client) -> None:
    """Every control endpoint on a key-missing bulb returns 412 before any driver call."""
    c, _, driver = client
    for path, body in [
        (f"/bulb/{_UNKEYED_MAC}/on", None),
        (f"/bulb/{_UNKEYED_MAC}/off", None),
        (f"/bulb/{_UNKEYED_MAC}/brightness", {"level": 50}),
        (f"/bulb/{_UNKEYED_MAC}/temp", {"kelvin": 4000}),
        (f"/bulb/{_UNKEYED_MAC}/color", {"r": 1, "g": 2, "b": 3}),
        (f"/bulb/{_UNKEYED_MAC}/scene", {"scene": "white"}),
    ]:
        r = c.post(path, json=body)
        assert r.status_code == 412, path
        detail = r.json()["detail"]
        assert "missing local_key" in detail["error"]
        assert "~/.config/tuya/keys.json" in detail["error"]
    # No driver call ever happened for the unkeyed bulb.
    assert driver.calls == []


def test_scenes_catalog_endpoint(client) -> None:
    c, *_ = client
    r = c.get("/scenes")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["scenes"]]
    assert "white" in names


def test_driver_error_returns_504(client) -> None:
    """A TuyaError from the driver surfaces as HTTP 504."""
    _c, reg, _ = client

    class FailingDriver(StubDriver):
        async def turn_on(self, ip: str, key: KeyEntry) -> dict:
            raise TuyaError("simulated udp timeout")

    app = create_app(
        registry=reg,
        driver=FailingDriver(),
        run_discovery=_noop_discover,
        keys_provider=lambda: {_KEYED_MAC: _key()},
        all_concurrency=16,
    )
    fc = TestClient(app)
    r = fc.post(f"/bulb/{_KEYED_MAC}/on")
    assert r.status_code == 504
    assert "simulated udp timeout" in r.json()["detail"]


def test_onboard_returns_501_structured(client) -> None:
    """/onboard ships as a 501 stub until Stream #1's ESP-TOUCH module lands."""
    c, *_ = client
    r = c.post("/onboard", json={"ssid": "home", "password": "pw", "timeout_s": 30})
    assert r.status_code == 501
    detail = r.json()["detail"]
    assert detail["error"] == "tuya_onboard_not_implemented"
    assert detail["requested"]["ssid"] == "home"


def test_onboard_validates_required_fields(client) -> None:
    c, *_ = client
    assert c.post("/onboard", json={"password": "pw"}).status_code == 422


def test_discover_endpoint(client) -> None:
    c, *_ = client
    r = c.post("/discover", json={"passive": True})
    assert r.status_code == 200
    body = r.json()
    assert body["discovered"] == 0
    assert body["total"] == 2


async def _noop_discover() -> int:
    return 0
