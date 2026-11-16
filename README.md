# RedFox Router (in progress)

Custom model/provider router + API key/usage observability for Danny Ford / RedFox systems.

## Goals (initial)
- Extend the existing API key registry (metadata + expiry reminders) to also track remaining usage/quota signals and window reset timing per key/provider where exposed.
- Build a backend that can power a future “RedFox Router” model routing layer: pick a working provider/key for a requested capability (initial focus: **DeepSeek Flash V4.1 FREE**), rotate when limits are hit, detect upstream issues, log them, and expose status.
- Provide a barebones dashboard UI now (to be replaced later by a “RedFox Team style / Koda PWA” dashboard), focused on: status, remaining requests/tokens (when available), reset countdowns, provider health, recent incidents.

## Current focus (v0)
- **Back-end first**. Frontend is intentionally minimal scaffolding.
- Start only with **DeepSeek Flash V4.1 FREE** use cases (NVIDIA NIM path known; also consider other free providers if they offer the same/compatible free model naming — to be researched).

## Related
- API key expiry tracker: `~/.claude/helpers/key_tracker.py` (SQLite at `~/.claude/data/api_keys.db`)
- This repo/project is the new home for the router + usage telemetry + dashboard work.
