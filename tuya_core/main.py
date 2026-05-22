"""FastAPI app entrypoint with lifespan-managed discovery loops."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import create_app
from .config import Settings
from .config import load as load_settings
from .discover import discover
from .driver import TuyaDriver
from .keys import KeyEntry, load_keys
from .registry import Registry

log = logging.getLogger(__name__)


def build_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    registry = Registry(cfg.state_path)
    driver = TuyaDriver()

    def keys_provider() -> dict[str, KeyEntry]:
        # Re-read on every call so an operator editing keys.json takes effect
        # on the next request without a daemon restart.
        return load_keys(cfg.keys_path)

    async def run_discovery() -> int:
        before = len(registry.all())
        bulbs = await discover(listen_s=cfg.discover_listen_s)
        for b in bulbs:
            registry.upsert_discovered(b)
        registry.flush()
        return len(registry.all()) - before

    async def refresh_loop() -> None:
        while True:
            await asyncio.sleep(cfg.refresh_interval_s)
            keys = keys_provider()
            for b in registry.all():
                key = keys.get(b.mac)
                if key is None:
                    continue  # cannot poll a bulb with no local_key
                try:
                    await driver.get_state(b.last_ip, key)
                    registry.upsert_discovered({
                        "mac": b.mac, "ip": b.last_ip,
                        "device_id": b.device_id,
                        "protocol_version": b.protocol_version,
                    })
                except Exception:
                    log.debug("refresh %s missed", b.mac)
            registry.flush()

    async def rediscover_loop() -> None:
        while True:
            await asyncio.sleep(cfg.discover_interval_s)
            try:
                await run_discovery()
            except Exception as e:
                log.warning("background rediscover failed: %r", e)

    async def _boot_discover() -> None:
        try:
            await run_discovery()
        except Exception as e:
            log.warning("boot discovery failed: %r", e)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Fire boot discovery in the background so uvicorn binds the port
        # immediately; /bulbs returns [] until the UDP listen window
        # (~3s) populates the registry. /health stays responsive throughout.
        t_boot = asyncio.create_task(_boot_discover())
        t1 = asyncio.create_task(refresh_loop())
        t2 = asyncio.create_task(rediscover_loop())
        try:
            yield
        finally:
            for t in (t_boot, t1, t2):
                t.cancel()
            await asyncio.gather(t_boot, t1, t2, return_exceptions=True)

    app = create_app(
        registry=registry,
        driver=driver,
        run_discovery=run_discovery,
        keys_provider=keys_provider,
        all_concurrency=cfg.all_concurrency,
    )
    app.router.lifespan_context = lifespan
    return app


app = build_app()
