# CLAUDE.md — tuya-core

Local HTTP daemon for Tuya-based smart bulbs (Amazon Basics et al.).

## Conventions

- Python 3.11+
- All identifiers (bulb IPs, device ids) come from env, the runtime
  registry, or `~/.config/tuya/keys.json`. **Never hard-code IPs.**
- Tuya local control via `tinytuya` (AES-128, protocol 3.1–3.4).
- Tests use `pytest`; `asyncio_mode = "auto"`. `tinytuya` is mocked at
  the `tuya_core.driver` boundary — tests never touch a real bulb.
- Run `ruff check`, `mypy`, `pytest -v` before commit.

## Local state (gitignored)

- `~/.config/tuya/state.json` — bulb registry (mode 0600)
- `~/.config/tuya/keys.json` — per-device AES local keys (mode 0600, SECRET)
- `~/.config/tuya/state.env` — env overrides

## SECURITY

- `keys.json` holds AES `local_key` secrets. It is gitignored, mode 0600,
  and **never logged**. `tuya_core.keys` warns the operator if the file
  mode is looser than 0600. Never echo a `local_key` into logs or API
  responses.

## systemd

- User unit: `~/.config/systemd/user/tuya-core.service`
  (copied from `systemd/tuya-core.service`)
- `systemctl --user restart tuya-core`
- `journalctl --user -u tuya-core -f`

## Don't repeat

- Only `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`,
  `ReadWritePaths=` work in user-scope systemd. Heavier `Protect*` knobs
  trip `status=218`.
- Boot discovery runs as `asyncio.create_task` inside the lifespan —
  never `await`'d before `yield`, or uvicorn's port-bind blocks ~3s.
- `tinytuya` is synchronous/blocking — the driver offloads every call to
  a thread via `asyncio.to_thread`. Don't call it directly from the loop.
- `/onboard` is a 501 stub until Stream #1's ESP-TOUCH module lands in
  wiz-core. See the follow-up task in the stream-5 plan.
