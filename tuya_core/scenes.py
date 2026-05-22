"""Built-in Tuya scene catalog.

Tuya scenes are device-specific and opaque. tuya-core ships a minimal
built-in set; anything else can be addressed as a bare integer scene index.
Every scene resolves to a (DPID, value) pair the driver writes via set_value.
DPID 21 is the conventional Tuya "work mode" / scene data point for bulbs.
"""

from __future__ import annotations

_WORK_MODE_DPID = 21

# name -> (dpid, value-string). Values are illustrative Tuya scene payloads;
# they are opaque to the daemon and passed straight through to the bulb.
SCENES: dict[str, tuple[int, str]] = {
    "white": (_WORK_MODE_DPID, "white"),
    "color cycle": (_WORK_MODE_DPID, "colour"),
    "music": (_WORK_MODE_DPID, "music"),
}


def resolve_scene(scene: str | int) -> tuple[int, str]:
    """Resolve a scene by built-in name or bare integer index.

    Returns (dpid, value). Raises ValueError on an unknown name.
    """
    if isinstance(scene, int):
        return (_WORK_MODE_DPID, f"scene_{scene}")
    s = scene.strip().lower()
    if s.isdigit():
        return (_WORK_MODE_DPID, f"scene_{int(s)}")
    if s in SCENES:
        return SCENES[s]
    raise ValueError(f"unknown scene: {scene!r}")
