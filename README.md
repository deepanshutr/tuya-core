# tuya-core

Local HTTP daemon that controls **Tuya**-based smart bulbs (e.g. Amazon
Basics) on the LAN via `tinytuya` (AES-128, protocol versions 3.1–3.4).
Sister to [wiz-core](https://github.com/deepanshutr/wiz-core).

- Port: `127.0.0.1:8768`
- Discovery: passive UDP broadcast listen on ports 6666 + 6667, MAC via ARP
- Multi-bulb registry keyed by MAC; persists to `~/.config/tuya/state.json`
- Identical HTTP contract to `wiz-core` (drop-in for the bulb multiplexer)

## Local keys — required for control

Tuya local control needs a per-device AES `local_key`. tuya-core reads
these from `~/.config/tuya/keys.json` (mode `0600`):

```json
{
  "d8a011deadbeef": {
    "device_id": "bf01abc1234567890",
    "local_key": "a1b2c3d4e5f6g7h8",
    "version": "3.3"
  }
}
```

Obtain keys out-of-band with `tinytuya wizard` (Tuya IoT developer
account), a Smart Life APK extraction, or a Home Assistant export. A bulb
with no key entry is still listed (`"key_missing": true`) but every
control endpoint returns **HTTP 412** until its key is supplied. This
file is gitignored and never logged — keep it `chmod 600`.

## Quick start

```bash
pip install -e .[dev]
tuya-core serve            # foreground
# or as a systemd user unit:
mkdir -p ~/.config/systemd/user
cp systemd/tuya-core.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tuya-core
```

## Onboarding

`POST /onboard` currently returns **501** — Tuya Wi-Fi onboarding via
ESP-TOUCH is gated on the shared module landing in `wiz-core` (Stream #1
of the unified bulb stack). Until then, onboard new bulbs with the
Smart Life / Tuya mobile app, then add their `local_key` to `keys.json`.

## Design

See `docs/superpowers/specs/2026-05-17-unified-bulb-stack-design.md`
(§4.3) and `docs/superpowers/specs/2026-05-19-unified-bulb-stack-amendments.md`.

## Sibling repos

- [wiz-core](https://github.com/deepanshutr/wiz-core) — Philips WiZ daemon
- [yeelight-core](https://github.com/deepanshutr/yeelight-core) — Yeelight daemon
- [bulb-cli](https://github.com/deepanshutr/bulb-cli) — Go multiplexer CLI
- [bulb-mcp](https://github.com/deepanshutr/bulb-mcp) — MCP stdio server
