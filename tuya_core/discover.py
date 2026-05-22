"""Passive LAN discovery for Tuya bulbs via UDP broadcast.

Tuya devices broadcast a status frame roughly once a second:
  - UDP 6666 — protocol 3.1/3.2, plaintext JSON
  - UDP 6667 — protocol 3.3+, AES-encrypted with Tuya's global UDP key

`tinytuya` decodes both. The broadcast header carries the device id
(`gwId`/`devId`) and protocol version but NOT the MAC, so the source IP is
ARP-resolved (`ip neigh`) to obtain a MAC — the registry's stable key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
from typing import Any

import tinytuya

log = logging.getLogger(__name__)

UDP_PORTS = (6666, 6667)
_DEFAULT_VERSION = "3.1"


def parse_broadcast(payload: dict[str, Any], src_ip: str) -> dict[str, Any]:
    """Normalise a decoded Tuya broadcast payload into a discovery dict.

    Raises ValueError if no device id is present.
    """
    device_id = payload.get("gwId") or payload.get("devId")
    if not device_id:
        raise ValueError(f"broadcast from {src_ip} missing gwId/devId: {payload!r}")
    return {
        "device_id": str(device_id),
        "ip": str(payload.get("ip", src_ip)),
        "protocol_version": str(payload.get("version", _DEFAULT_VERSION)),
    }


def _run_ip_neigh() -> str:
    """Return the output of `ip neigh`. Isolated for test monkeypatching."""
    return subprocess.run(
        ["ip", "neigh"], capture_output=True, text=True, timeout=2, check=False
    ).stdout


def arp_lookup(ip: str) -> str | None:
    """Resolve `ip` to a normalised 12-hex-char MAC via the kernel ARP table.

    Returns None if the IP is not in the table or the command fails.
    """
    try:
        table = _run_ip_neigh()
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("ip neigh failed: %r", exc)
        return None
    for line in table.splitlines():
        parts = line.split()
        if parts and parts[0] == ip and "lladdr" in parts:
            mac = parts[parts.index("lladdr") + 1]
            return "".join(c for c in mac.lower() if c in "0123456789abcdef")
    return None


def _decode_packet(data: bytes) -> dict[str, Any]:
    """Decode one raw Tuya UDP broadcast payload to a dict.

    6666 frames are plaintext JSON; 6667 frames are AES-encrypted. tinytuya's
    decrypt_udp handles the encrypted case; a plaintext frame falls through to
    a direct JSON parse. Raises ValueError on anything undecodable.
    """
    try:
        return dict(tinytuya.decrypt_udp(data))
    except Exception:  # tinytuya raises a variety of errors; catch all
        pass
    try:
        return dict(json.loads(data.decode()))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"undecodable Tuya broadcast: {exc}") from exc


async def _collect_broadcasts(listen_s: float) -> list[tuple[bytes, str]]:
    """Listen on UDP 6666+6667 for `listen_s` seconds; return (data, src_ip) pairs."""
    loop = asyncio.get_running_loop()
    received: list[tuple[bytes, str]] = []

    class _Collector(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            received.append((data, addr[0]))

    transports: list[asyncio.DatagramTransport] = []
    for port in UDP_PORTS:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError as exc:
            log.warning("cannot bind UDP %d for discovery: %r", port, exc)
            sock.close()
            continue
        transport, _ = await loop.create_datagram_endpoint(_Collector, sock=sock)
        transports.append(transport)

    try:
        await asyncio.sleep(listen_s)
    finally:
        for t in transports:
            t.close()
    return received


async def discover(*, listen_s: float = 3.0) -> list[dict[str, Any]]:
    """Discover Tuya bulbs by listening for UDP broadcasts.

    Returns a list of normalised bulb dicts deduped by MAC. Packets that
    cannot be decoded, lack a device id, or whose IP cannot be ARP-resolved
    to a MAC are skipped (a MAC is required as the registry key).
    """
    raw = await _collect_broadcasts(listen_s)
    seen: dict[str, dict[str, Any]] = {}
    for data, src_ip in raw:
        try:
            payload = _decode_packet(data)
        except ValueError as exc:
            log.debug("dropping undecodable broadcast from %s: %r", src_ip, exc)
            continue
        try:
            parsed = parse_broadcast(payload, src_ip)
        except ValueError as exc:
            log.debug("dropping broadcast with no device id: %r", exc)
            continue
        mac = arp_lookup(parsed["ip"])
        if mac is None:
            log.debug("no ARP entry for %s; skipping device %s",
                      parsed["ip"], parsed["device_id"])
            continue
        seen[mac] = {"mac": mac, **parsed}
    return list(seen.values())
