"""Per-MAC bulb registry, persisted to a 0600-mode state.json."""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _normalise_mac(s: str) -> str:
    return "".join(c for c in s.lower() if c in "0123456789abcdef")


@dataclass
class Bulb:
    mac: str
    name: str
    last_ip: str
    device_id: str | None = None
    protocol_version: str | None = None
    discovered_at: str = field(default_factory=_now_iso)
    last_seen: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "last_ip": self.last_ip,
            "device_id": self.device_id,
            "protocol_version": self.protocol_version,
            "discovered_at": self.discovered_at,
            "last_seen": self.last_seen,
        }


class Registry:
    """In-memory registry backed by `path` (JSON, 0600)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._bulbs: dict[str, Bulb] = {}
        self._load()

    # ---- Persistence ----

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            blob = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return
        for mac, raw in blob.get("bulbs", {}).items():
            self._bulbs[mac] = Bulb(
                mac=mac,
                name=raw.get("name", f"bulb-{len(self._bulbs) + 1}"),
                last_ip=raw["last_ip"],
                device_id=raw.get("device_id"),
                protocol_version=raw.get("protocol_version"),
                discovered_at=raw.get("discovered_at", _now_iso()),
                last_seen=raw.get("last_seen", _now_iso()),
            )

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = {
            "version": 1,
            "bulbs": {mac: b.to_dict() for mac, b in self._bulbs.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(blob, indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ---- Mutators ----

    def upsert_discovered(self, raw: dict[str, Any]) -> Bulb:
        """Idempotently add/refresh a bulb from a discovery dict."""
        mac = _normalise_mac(raw["mac"])
        ip = raw["ip"]
        now = _now_iso()
        if mac in self._bulbs:
            b = self._bulbs[mac]
            b.last_ip = ip
            b.last_seen = now
            if raw.get("device_id"):
                b.device_id = raw["device_id"]
            if raw.get("protocol_version"):
                b.protocol_version = raw["protocol_version"]
        else:
            b = Bulb(
                mac=mac,
                name=f"bulb-{len(self._bulbs) + 1}",
                last_ip=ip,
                device_id=raw.get("device_id"),
                protocol_version=raw.get("protocol_version"),
                discovered_at=now,
                last_seen=now,
            )
            self._bulbs[mac] = b
        return b

    def rename(self, mac: str, new_name: str) -> Bulb:
        mac = _normalise_mac(mac)
        if mac not in self._bulbs:
            raise KeyError(mac)
        b = self._bulbs[mac]
        b.name = new_name
        return b

    # ---- Lookups ----

    def all(self) -> list[Bulb]:
        return list(self._bulbs.values())

    def default(self) -> Bulb | None:
        if not self._bulbs:
            return None
        # Tie-break by insertion order when discovered_at strings compare
        # equal. Python dicts preserve insertion order.
        indexed = enumerate(self._bulbs.values())
        return min(indexed, key=lambda pair: (pair[1].discovered_at, pair[0]))[1]

    def resolve(self, target: str | None) -> Bulb | None:
        """Resolve target per spec rules. None/empty/"_default" => default().

        Note: "all" is intentionally NOT handled here — the API layer routes
        it to the broadcast handler before calling resolve().
        """
        if not target or target == "_default":
            return self.default()
        mac_try = _normalise_mac(target)
        if len(mac_try) == 12 and mac_try in self._bulbs:
            return self._bulbs[mac_try]
        try:
            ip = str(ipaddress.IPv4Address(target))
            for b in self._bulbs.values():
                if b.last_ip == ip:
                    return b
        except (ipaddress.AddressValueError, ValueError):
            pass
        t = target.strip().lower()
        for b in self._bulbs.values():
            if b.name.lower() == t:
                return b
        return None
