"""Loader for ~/.config/tuya/keys.json — per-device AES local keys.

SECURITY: the values in this file are secrets. This module never logs a
`local_key`. It only reads the file; the operator populates it out-of-band
(e.g. `tinytuya wizard`). The file is expected to be mode 0600.
"""

from __future__ import annotations

import json
import logging
import stat
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_VERSION = "3.3"


def _normalise_mac(s: str) -> str:
    return "".join(c for c in s.lower() if c in "0123456789abcdef")


@dataclass(frozen=True)
class KeyEntry:
    """One device's local-control credentials. Never log `local_key`."""

    device_id: str
    local_key: str
    version: str = _DEFAULT_VERSION


def load_keys(path: Path) -> dict[str, KeyEntry]:
    """Read keys.json into a {mac: KeyEntry} map.

    Missing file -> {}. Corrupt JSON -> {} (logged). Entries missing a
    required field (`device_id` or `local_key`) are skipped with a warning
    that names the MAC but NEVER the key. A file looser than 0600 is loaded
    but warned about.
    """
    if not path.exists():
        return {}

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        log.warning(
            "keys file %s is mode %o; should be 0600 (chmod 600 it)", path, mode
        )

    try:
        blob = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.error("keys file %s is unreadable, treating as empty: %r", path, exc)
        return {}

    out: dict[str, KeyEntry] = {}
    for raw_mac, raw in blob.items():
        if not isinstance(raw, dict):
            log.warning("keys entry for %s is not an object; skipped", raw_mac)
            continue
        device_id = raw.get("device_id")
        local_key = raw.get("local_key")
        if not device_id or not local_key:
            # Names the MAC only — never the key.
            log.warning(
                "keys entry for %s missing device_id/local_key; skipped", raw_mac
            )
            continue
        out[_normalise_mac(raw_mac)] = KeyEntry(
            device_id=str(device_id),
            local_key=str(local_key),
            version=str(raw.get("version", _DEFAULT_VERSION)),
        )
    return out
