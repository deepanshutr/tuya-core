"""FastAPI HTTP surface — identical contract to wiz-core, plus Tuya 412 path."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .driver import TuyaError
from .keys import KeyEntry
from .registry import Bulb, Registry
from .scenes import SCENES, resolve_scene


class _TuyaDriver(Protocol):
    async def get_state(self, ip: str, key: KeyEntry) -> dict[str, Any]: ...
    async def turn_on(self, ip: str, key: KeyEntry) -> dict[str, Any]: ...
    async def turn_off(self, ip: str, key: KeyEntry) -> dict[str, Any]: ...
    async def set_brightness(
        self, ip: str, key: KeyEntry, *, level: int
    ) -> dict[str, Any]: ...
    async def set_temp(self, ip: str, key: KeyEntry, *, kelvin: int) -> dict[str, Any]: ...
    async def set_color(
        self, ip: str, key: KeyEntry, *, r: int, g: int, b: int
    ) -> dict[str, Any]: ...
    async def set_scene(
        self, ip: str, key: KeyEntry, *, dpid: int, value: Any
    ) -> dict[str, Any]: ...


KeysProvider = Callable[[], dict[str, KeyEntry]]


class BrightnessIn(BaseModel):
    level: Annotated[int, Field(ge=10, le=100)]


class TempIn(BaseModel):
    kelvin: Annotated[int, Field(ge=2200, le=6500)]


class ColorIn(BaseModel):
    r: Annotated[int, Field(ge=0, le=255)]
    g: Annotated[int, Field(ge=0, le=255)]
    b: Annotated[int, Field(ge=0, le=255)]


class SceneIn(BaseModel):
    scene: str | int
    speed: int | None = Field(None, ge=10, le=200)


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class DiscoverIn(BaseModel):
    passive: bool = False


class OnboardIn(BaseModel):
    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    timeout_s: int = Field(60, ge=10, le=300)


def _bulb_payload(b: Bulb, *, key_missing: bool) -> dict[str, Any]:
    """Registry entry -> /bulbs entry. Never includes local_key material."""
    return {
        "protocol": "tuya",
        "mac": b.mac,
        "name": b.name,
        "ip": b.last_ip,
        "rssi": None,  # Tuya broadcasts carry no RSSI
        "device_id": b.device_id,
        "protocol_version": b.protocol_version,
        "discovered_at": b.discovered_at,
        "last_seen": b.last_seen,
        "key_missing": key_missing,
    }


def create_app(
    *,
    registry: Registry,
    driver: _TuyaDriver,
    run_discovery: Callable[[], Coroutine[Any, Any, int]],
    keys_provider: KeysProvider,
    all_concurrency: int = 16,
) -> FastAPI:
    app = FastAPI(title="tuya-core")

    def resolve_or_404(target: str) -> Bulb:
        b = registry.resolve(target)
        if b is None:
            raise HTTPException(status_code=404, detail=f"no bulb matches {target!r}")
        return b

    def key_or_412(b: Bulb) -> KeyEntry:
        """Return the bulb's KeyEntry, or raise 412 if no key is configured."""
        key = keys_provider().get(b.mac)
        if key is None:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": (
                        f"missing local_key for {b.mac}; "
                        "populate ~/.config/tuya/keys.json"
                    )
                },
            )
        return key

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/bulbs")
    async def list_bulbs() -> dict[str, Any]:
        keys = keys_provider()
        return {
            "bulbs": [
                _bulb_payload(b, key_missing=b.mac not in keys)
                for b in registry.all()
            ]
        }

    @app.get("/bulbs/default")
    async def default_bulb() -> dict[str, Any]:
        b = registry.default()
        if b is None:
            raise HTTPException(409, "no bulbs known; POST /discover first")
        key = key_or_412(b)
        payload = _bulb_payload(b, key_missing=False)
        try:
            state = await driver.get_state(b.last_ip, key)
        except TuyaError as e:
            raise HTTPException(504, str(e)) from e
        return {**payload, **state}

    @app.post("/discover")
    async def discover(body: DiscoverIn) -> dict[str, Any]:
        n = await run_discovery()
        registry.flush()
        return {"discovered": n, "total": len(registry.all())}

    @app.post("/onboard")
    async def onboard_route(body: OnboardIn) -> dict[str, Any]:
        # Tuya bulbs in setup mode (ESP_* SSID) use Espressif's ESP-TOUCH
        # protocol — the SAME module wiz-core gains in Stream #1. Until that
        # lands and its public API stabilises, /onboard returns 501 with a
        # structured envelope (mirrors wiz-core's pre-amendment stub).
        # The final task(s) of this plan swap this for the real call.
        # See amendment §A1 "Tuya-core dependency".
        raise HTTPException(
            status_code=501,
            detail={
                "error": "tuya_onboard_not_implemented",
                "message": (
                    "Tuya ESP-TOUCH onboarding is not implemented yet. It is "
                    "gated on Stream #1 landing the shared ESP-TOUCH module in "
                    "wiz-core. Use the Smart Life / Tuya mobile app to onboard "
                    "new bulbs; they appear in the registry within ~10min via "
                    "the background rediscover loop. Then populate "
                    "~/.config/tuya/keys.json with the device's local_key."
                ),
                "requested": {"ssid": body.ssid, "timeout_s": body.timeout_s},
            },
        )

    @app.get("/scenes")
    async def scenes() -> dict[str, Any]:
        return {
            "scenes": [
                {"name": nm, "dpid": dpid, "value": val}
                for nm, (dpid, val) in sorted(SCENES.items())
            ]
        }

    # NOTE: /bulb/all/* routes are registered BEFORE /bulb/{target}/* to
    # ensure the literal "all" segment is matched first (Starlette does not
    # auto-rank static segments over path params when registered after).
    _register_all_routes(
        app,
        registry=registry,
        driver=driver,
        keys_provider=keys_provider,
        all_concurrency=all_concurrency,
    )

    @app.get("/bulb/{target}")
    async def get_bulb(target: str) -> dict[str, Any]:
        b = resolve_or_404(target)
        key = key_or_412(b)
        payload = _bulb_payload(b, key_missing=False)
        try:
            state = await driver.get_state(b.last_ip, key)
        except TuyaError as e:
            raise HTTPException(504, str(e)) from e
        return {**payload, **state}

    async def _control(
        b: Bulb, op: Callable[[str, KeyEntry], Coroutine[Any, Any, dict[str, Any]]]
    ) -> dict[str, Any]:
        key = key_or_412(b)
        try:
            return await op(b.last_ip, key)
        except TuyaError as e:
            raise HTTPException(504, str(e)) from e

    @app.post("/bulb/{target}/on")
    async def on(target: str) -> dict[str, Any]:
        return await _control(resolve_or_404(target), driver.turn_on)

    @app.post("/bulb/{target}/off")
    async def off(target: str) -> dict[str, Any]:
        return await _control(resolve_or_404(target), driver.turn_off)

    @app.post("/bulb/{target}/brightness")
    async def brightness(target: str, body: BrightnessIn) -> dict[str, Any]:
        return await _control(
            resolve_or_404(target),
            lambda ip, k: driver.set_brightness(ip, k, level=body.level),
        )

    @app.post("/bulb/{target}/temp")
    async def temp(target: str, body: TempIn) -> dict[str, Any]:
        return await _control(
            resolve_or_404(target),
            lambda ip, k: driver.set_temp(ip, k, kelvin=body.kelvin),
        )

    @app.post("/bulb/{target}/color")
    async def color(target: str, body: ColorIn) -> dict[str, Any]:
        return await _control(
            resolve_or_404(target),
            lambda ip, k: driver.set_color(ip, k, r=body.r, g=body.g, b=body.b),
        )

    @app.post("/bulb/{target}/scene")
    async def scene(target: str, body: SceneIn) -> dict[str, Any]:
        try:
            dpid, value = resolve_scene(body.scene)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return await _control(
            resolve_or_404(target),
            lambda ip, k: driver.set_scene(ip, k, dpid=dpid, value=value),
        )

    @app.post("/bulb/{target}/name")
    async def name(target: str, body: NameIn) -> dict[str, Any]:
        b = resolve_or_404(target)
        registry.rename(b.mac, body.name)
        registry.flush()
        return _bulb_payload(b, key_missing=b.mac not in keys_provider())

    return app


# ---- /bulb/all/{op} broadcast family (amendment §A2) — added in Task 9 ----


def _register_all_routes(
    app: FastAPI,
    *,
    registry: Registry,
    driver: _TuyaDriver,
    keys_provider: KeysProvider,
    all_concurrency: int,
) -> None:
    """Placeholder; the broadcast family is implemented in Task 9."""
    return None
