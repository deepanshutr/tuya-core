"""Async wrapper over `tinytuya` for Tuya bulb control.

tinytuya's API is synchronous and blocking. Each call is offloaded to a
worker thread via `asyncio.to_thread` so the FastAPI event loop is never
blocked. A fresh `BulbDevice` is built per call — tinytuya devices are not
safe to share across concurrent callers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import tinytuya

from .keys import KeyEntry

log = logging.getLogger(__name__)

# Tuya colour-temp DPID range is 0..1000 percent-scaled by tinytuya's
# set_colourtemp_percentage (0..100). We map the contract's Kelvin window.
_KELVIN_MIN = 2200
_KELVIN_MAX = 6500


class TuyaError(RuntimeError):
    """Raised when a Tuya call fails (network error or tinytuya error envelope)."""


def kelvin_to_percent(kelvin: int) -> int:
    """Map a Kelvin value in [2200, 6500] linearly to an integer percent [0, 100].

    Values outside the window are clamped to the nearest endpoint.
    """
    clamped = max(_KELVIN_MIN, min(_KELVIN_MAX, kelvin))
    span = _KELVIN_MAX - _KELVIN_MIN
    return round((clamped - _KELVIN_MIN) / span * 100)


def _check(resp: Any) -> dict[str, Any]:
    """Normalise a tinytuya response; raise TuyaError on an error envelope."""
    if isinstance(resp, dict) and ("Error" in resp or "Err" in resp):
        raise TuyaError(
            f"tuya error {resp.get('Err')}: {resp.get('Error')}"
        )
    return dict(resp) if isinstance(resp, dict) else {}


class TuyaDriver:
    """Stateless Tuya client. Safe for concurrent use; builds a device per call."""

    def _device(self, ip: str, key: KeyEntry) -> tinytuya.BulbDevice:
        dev = tinytuya.BulbDevice(key.device_id, ip, key.local_key)
        dev.set_version(float(key.version))
        return dev

    async def _run(self, fn_name: str, ip: str, key: KeyEntry, *args: Any) -> dict[str, Any]:
        def call() -> Any:
            dev = self._device(ip, key)
            method = getattr(dev, fn_name)
            return method(*args)

        try:
            resp = await asyncio.to_thread(call)
        except TuyaError:
            raise
        except Exception as exc:  # tinytuya raises bare OSError/socket errors
            raise TuyaError(f"{fn_name} to {ip}: {exc}") from exc
        return _check(resp)

    async def get_state(self, ip: str, key: KeyEntry) -> dict[str, Any]:
        return await self._run("status", ip, key)

    async def turn_on(self, ip: str, key: KeyEntry) -> dict[str, Any]:
        return await self._run("turn_on", ip, key)

    async def turn_off(self, ip: str, key: KeyEntry) -> dict[str, Any]:
        return await self._run("turn_off", ip, key)

    async def set_brightness(self, ip: str, key: KeyEntry, *, level: int) -> dict[str, Any]:
        return await self._run("set_brightness_percentage", ip, key, level)

    async def set_temp(self, ip: str, key: KeyEntry, *, kelvin: int) -> dict[str, Any]:
        return await self._run(
            "set_colourtemp_percentage", ip, key, kelvin_to_percent(kelvin)
        )

    async def set_color(
        self, ip: str, key: KeyEntry, *, r: int, g: int, b: int
    ) -> dict[str, Any]:
        return await self._run("set_colour", ip, key, r, g, b)

    async def set_scene(
        self, ip: str, key: KeyEntry, *, dpid: int, value: Any
    ) -> dict[str, Any]:
        return await self._run("set_value", ip, key, dpid, value)
