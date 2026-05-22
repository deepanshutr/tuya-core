"""Tuya UDP broadcast discovery: header parse, ARP resolve, listener."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tuya_core.discover import arp_lookup, discover, parse_broadcast


def test_parse_broadcast_extracts_devid_and_version() -> None:
    payload = {"ip": "192.168.1.7", "gwId": "bf01abc99", "version": "3.3"}
    parsed = parse_broadcast(payload, src_ip="192.168.1.7")
    assert parsed["device_id"] == "bf01abc99"
    assert parsed["ip"] == "192.168.1.7"
    assert parsed["protocol_version"] == "3.3"


def test_parse_broadcast_falls_back_to_devid_key() -> None:
    """Some firmwares use `devId` instead of `gwId`."""
    payload = {"devId": "bf02devkey", "version": "3.4"}
    parsed = parse_broadcast(payload, src_ip="192.168.1.8")
    assert parsed["device_id"] == "bf02devkey"
    assert parsed["ip"] == "192.168.1.8"
    assert parsed["protocol_version"] == "3.4"


def test_parse_broadcast_defaults_version_when_absent() -> None:
    payload = {"gwId": "bf03"}
    parsed = parse_broadcast(payload, src_ip="192.168.1.9")
    assert parsed["protocol_version"] == "3.1"


def test_parse_broadcast_missing_devid_raises() -> None:
    with pytest.raises(ValueError, match="missing gwId/devId"):
        parse_broadcast({"version": "3.3"}, src_ip="192.168.1.9")


def test_arp_lookup_parses_ip_neigh_output() -> None:
    sample = "192.168.1.7 dev wlo1 lladdr d8:a0:11:de:ad:be REACHABLE\n"
    with patch("tuya_core.discover._run_ip_neigh", return_value=sample):
        mac = arp_lookup("192.168.1.7")
    assert mac == "d8a011deadbe"


def test_arp_lookup_returns_none_when_ip_absent() -> None:
    sample = "192.168.1.99 dev wlo1  FAILED\n"
    with patch("tuya_core.discover._run_ip_neigh", return_value=sample):
        assert arp_lookup("192.168.1.7") is None


def test_arp_lookup_returns_none_on_command_failure() -> None:
    with patch("tuya_core.discover._run_ip_neigh", side_effect=OSError("no ip cmd")):
        assert arp_lookup("192.168.1.7") is None


async def test_discover_parses_packets_and_resolves_macs() -> None:
    """discover() collects broadcast payloads, parses them, ARP-resolves MACs."""
    raw_packets = [
        json.dumps({"gwId": "bf01abc", "ip": "192.168.1.7", "version": "3.3"}).encode(),
        json.dumps({"gwId": "bf02xyz", "ip": "192.168.1.8", "version": "3.4"}).encode(),
    ]
    arp_table = {"192.168.1.7": "aaaaaaaaaaaa", "192.168.1.8": "bbbbbbbbbbbb"}

    async def fake_collect(listen_s: float) -> list[tuple[bytes, str]]:
        return [(raw_packets[0], "192.168.1.7"), (raw_packets[1], "192.168.1.8")]

    def fake_decode(data: bytes) -> dict:
        return json.loads(data.decode())

    with (
        patch("tuya_core.discover._collect_broadcasts", side_effect=fake_collect),
        patch("tuya_core.discover._decode_packet", side_effect=fake_decode),
        patch("tuya_core.discover.arp_lookup", side_effect=arp_table.get),
    ):
        bulbs = await discover(listen_s=0.0)

    by_mac = {b["mac"]: b for b in bulbs}
    assert set(by_mac) == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}
    assert by_mac["aaaaaaaaaaaa"]["device_id"] == "bf01abc"
    assert by_mac["aaaaaaaaaaaa"]["protocol_version"] == "3.3"
    assert by_mac["bbbbbbbbbbbb"]["ip"] == "192.168.1.8"


async def test_discover_skips_packet_with_unresolvable_mac() -> None:
    """A broadcast whose IP has no ARP entry is dropped (no MAC = no registry key)."""
    pkt = json.dumps({"gwId": "bf01abc", "ip": "192.168.1.7", "version": "3.3"}).encode()

    async def fake_collect(listen_s: float) -> list[tuple[bytes, str]]:
        return [(pkt, "192.168.1.7")]

    with (
        patch("tuya_core.discover._collect_broadcasts", side_effect=fake_collect),
        patch("tuya_core.discover._decode_packet", side_effect=lambda d: json.loads(d.decode())),
        patch("tuya_core.discover.arp_lookup", return_value=None),
    ):
        bulbs = await discover(listen_s=0.0)
    assert bulbs == []


async def test_discover_dedupes_repeated_broadcasts_by_devid() -> None:
    """Tuya broadcasts ~1Hz; the same device appears many times in one window."""
    pkt = json.dumps({"gwId": "bf01abc", "ip": "192.168.1.7", "version": "3.3"}).encode()

    async def fake_collect(listen_s: float) -> list[tuple[bytes, str]]:
        return [(pkt, "192.168.1.7"), (pkt, "192.168.1.7"), (pkt, "192.168.1.7")]

    with (
        patch("tuya_core.discover._collect_broadcasts", side_effect=fake_collect),
        patch("tuya_core.discover._decode_packet", side_effect=lambda d: json.loads(d.decode())),
        patch("tuya_core.discover.arp_lookup", return_value="aaaaaaaaaaaa"),
    ):
        bulbs = await discover(listen_s=0.0)
    assert len(bulbs) == 1


async def test_discover_drops_undecodable_packet() -> None:
    """A packet tinytuya cannot decrypt is logged and skipped, not fatal."""
    good = json.dumps({"gwId": "bf01abc", "ip": "192.168.1.7", "version": "3.3"}).encode()

    async def fake_collect(listen_s: float) -> list[tuple[bytes, str]]:
        return [(b"\x00garbage", "192.168.1.5"), (good, "192.168.1.7")]

    def fake_decode(data: bytes) -> dict:
        if data == good:
            return json.loads(data.decode())
        raise ValueError("cannot decrypt")

    with (
        patch("tuya_core.discover._collect_broadcasts", side_effect=fake_collect),
        patch("tuya_core.discover._decode_packet", side_effect=fake_decode),
        patch("tuya_core.discover.arp_lookup", return_value="aaaaaaaaaaaa"),
    ):
        bulbs = await discover(listen_s=0.0)
    assert len(bulbs) == 1
    assert bulbs[0]["device_id"] == "bf01abc"
