# GitHub Secrets used by this repo

Defined under: **Repo Settings → Secrets and variables → Actions**.

| Secret | Used in | Purpose |
|--------|---------|---------|
| `TG_BOT_TOKEN` | `release.yml` | Bot that posts release-notifications to the operator's Telegram. Optional — workflow no-ops if unset. |
| `TG_CHAT_ID`   | `release.yml` | Chat ID to receive release notifications. |

This file is **only documentation** — no secret values live here.

## NOT a GitHub secret

The per-device Tuya AES `local_key`s live in `~/.config/tuya/keys.json`
on the host (mode 0600), are gitignored, and are **never** committed or
placed in CI. They are operator-supplied out-of-band (`tinytuya wizard`).
