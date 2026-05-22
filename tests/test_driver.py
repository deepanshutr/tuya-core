"""Tuya driver — tinytuya mocked at the module boundary."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from tuya_core.driver import TuyaDriver, TuyaError, kelvin_to_percent
from tuya_core.keys import KeyEntry


@pytest.fixture()
def fake_tinytuya(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace tuya_core.driver.tinytuya with a mock; return the BulbDevice mock."""
    device = MagicMock(name="BulbDevice")
    device.status.return_value = {"dps": {"20": True, "22": 50, "23": 500}}
    device.turn_on.return_value = {"dps": {"20": True}}
    device.turn_off.return_value = {"dps": {"20": False}}
    device.set_brightness_percentage.return_value = {"dps": {"22": 70}}
    device.set_colourtemp_percentage.return_value = {"dps": {"23": 40}}
    device.set_colour.return_value = {"dps": {"24": "..."}}
    device.set_value.return_value = {"dps": {"21": "scene"}}

    fake_mod = MagicMock(name="tinytuya")
    fake_mod.BulbDevice.return_value = device
    monkeypatch.setattr("tuya_core.driver.tinytuya", fake_mod)
    return device


def _key() -> KeyEntry:
    return KeyEntry(device_id="bf01abc", local_key="a1b2c3d4e5f6g7h8", version="3.3")


def test_kelvin_to_percent_endpoints() -> None:
    assert kelvin_to_percent(2200) == 0
    assert kelvin_to_percent(6500) == 100
    assert kelvin_to_percent(4350) == 50


def test_kelvin_to_percent_clamps_out_of_range() -> None:
    assert kelvin_to_percent(1000) == 0
    assert kelvin_to_percent(9999) == 100


async def test_get_state_returns_dps(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    out = await drv.get_state("192.168.1.5", _key())
    assert out == {"dps": {"20": True, "22": 50, "23": 500}}


async def test_turn_on_calls_tinytuya(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    await drv.turn_on("192.168.1.5", _key())
    fake_tinytuya.turn_on.assert_called_once()


async def test_turn_off_calls_tinytuya(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    await drv.turn_off("192.168.1.5", _key())
    fake_tinytuya.turn_off.assert_called_once()


async def test_set_brightness_passes_percent(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    await drv.set_brightness("192.168.1.5", _key(), level=70)
    fake_tinytuya.set_brightness_percentage.assert_called_once_with(70)


async def test_set_temp_converts_kelvin_to_percent(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    await drv.set_temp("192.168.1.5", _key(), kelvin=4350)
    fake_tinytuya.set_colourtemp_percentage.assert_called_once_with(50)


async def test_set_color_passes_rgb(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    await drv.set_color("192.168.1.5", _key(), r=255, g=0, b=100)
    fake_tinytuya.set_colour.assert_called_once_with(255, 0, 100)


async def test_set_scene_writes_dpid(fake_tinytuya: MagicMock) -> None:
    drv = TuyaDriver()
    await drv.set_scene("192.168.1.5", _key(), dpid=21, value="scene_data")
    fake_tinytuya.set_value.assert_called_once_with(21, "scene_data")


async def test_driver_constructs_device_with_key_fields(fake_tinytuya: MagicMock) -> None:
    """tinytuya.BulbDevice is built with device_id, ip, local_key, and version."""
    import tuya_core.driver as drvmod

    drv = TuyaDriver()
    await drv.turn_on("192.168.1.5", _key())
    drvmod.tinytuya.BulbDevice.assert_called_once_with(
        "bf01abc", "192.168.1.5", "a1b2c3d4e5f6g7h8"
    )
    fake_tinytuya.set_version.assert_called_once_with(3.3)


async def test_tinytuya_error_response_raises_tuyaerror(fake_tinytuya: MagicMock) -> None:
    """A tinytuya {'Error': ...} envelope becomes a TuyaError."""
    fake_tinytuya.turn_on.return_value = {"Error": "Network Error", "Err": "905"}
    drv = TuyaDriver()
    with pytest.raises(TuyaError, match="905"):
        await drv.turn_on("192.168.1.5", _key())


async def test_tinytuya_exception_raises_tuyaerror(fake_tinytuya: MagicMock) -> None:
    """A raw exception from tinytuya is wrapped as TuyaError, not leaked."""
    fake_tinytuya.status.side_effect = OSError("connection refused")
    drv = TuyaDriver()
    with pytest.raises(TuyaError, match="connection refused"):
        await drv.get_state("192.168.1.5", _key())
