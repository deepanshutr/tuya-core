"""Built-in Tuya scene catalog: name -> (dpid, value) lookup."""

from __future__ import annotations

import pytest

from tuya_core.scenes import SCENES, resolve_scene


def test_catalog_has_builtin_scenes() -> None:
    assert "white" in SCENES
    assert "color cycle" in SCENES
    assert "music" in SCENES


def test_resolve_by_name_case_insensitive() -> None:
    dpid, value = resolve_scene("white")
    assert dpid == 21
    assert isinstance(value, str)
    assert resolve_scene("WHITE") == resolve_scene("white")
    assert resolve_scene(" Color Cycle ") == resolve_scene("color cycle")


def test_resolve_unknown_scene_raises() -> None:
    with pytest.raises(ValueError, match="unknown scene"):
        resolve_scene("disco-party-9000")


def test_resolve_accepts_int_scene_as_opaque_dpid_value() -> None:
    """A bare int is treated as an opaque scene index written to the work-mode DPID."""
    dpid, value = resolve_scene(7)
    assert dpid == 21
    assert value == "scene_7"
