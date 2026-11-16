# RedFox Router — Build Log

> Living log. Append entries as work/research happens. This is the source of truth for decisions, research rounds, and implementation notes.

---

## 2026-11-15 — Kickoff (session start)

### Context (from Danny)
- We already have an “API key registry system” (`~/.claude/helpers/key_tracker.py`) that tracks API key expiry dates.
- Want to go further: **track remaining usage on each key and when usage resets**, build toward a **v2 “model router”** that understands remaining requests/quotas per key and rotates them as each hits limits. User should be able to pick a custom model router in KiloCode and see something like: **“RedFox Router: DeepSeek Flash V4.1 FREE”**.
- **Current focus:** only **DeepSeek Flash V4.1 FREE** for now.
- We already have an **NVIDIA API key** set up for free use of this model; it is currently **not working** (may be limits hit or temporary upstream issue). Router should be able to **detect upstream issues**, switch to another provider when possible, **log the issue**, and show it on the dashboard.
- Create a **custom dashboard** (barebones now) showing status, remaining requests/tokens, window reset time remaining, etc., with the understanding it will later be replaced by a **“RedFox Team style dashboard”** that is part of the **Koda system / Koda PWA**.
- **Back-end first.** Frontend barebones scaffolding only.
- **Request:** create a new project (RedFox Router), create a build log and write all this into it, and **kick off multiple deep comprehensive rounds of research** (think between rounds; figure out what else to research).

### Known existing pieces (from repo scan)
- `~/.claude/helpers/key_tracker.py` + `key_tracker.armory.yaml` + DB `~/.claude/data/api_keys.db` (SQLite). Current schema tracks: project, provider, identifier, created/expires, policy, status, rotation/notify metadata. No usage/quota/reset fields today.
- Key registry entries (from DB snapshot today): includes **RedFox Software Factory / nVidia / “NVIDIA NIM (deepseek-v4.1-flash, nemotron-3-ultra)”** (expires 2027-02-11, notes mention free tier). Also other providers (Gemini, Groq, OpenRouter) recorded.

### Open questions to drive research
1. **Exact model identity/naming**: What is the canonical model id/name for **“DeepSeek Flash V4.1 FREE”** across providers? (NVIDIA NIM, OpenRouter `:free`, any others?) Are there multiple variants (context length, quantization) advertised differently?
2. **Provider landscape (free tier)** for this model: Which providers offer it free? What are their rate limits (RPM/TPM/requests per day/window), quota units, and **how limits are communicated** (response headers, error codes like 429, separate quota APIs)?
3. **NVIDIA NIM specifics**: Current behavior of the NVIDIA key for this model (is it 404/model-not-found vs 429/rate-limited vs auth issues?). What headers/docs exist for usage/quota visibility? (e.g., `x-ratelimit-*`, usage endpoints?)
4. **OpenAI-compatible surface area**: Many providers expose OpenAI-style APIs; does the “model router” need to be OpenAI-compatible for KiloCode integration, or can it be a custom HTTP service that KiloCode points to? Need to research KiloCode/custom provider/router patterns.
5. **Quota telemetry patterns**: Best practices for polling vs passive capture from responses, storing time-windowed usage, reset time math (UTC vs provider clocks), and handling providers that don’t expose remaining counts.
6. **Failure classification**: Distinguish transient upstream errors (5xx), rate limits (429), model unavailable, auth/key invalid, region blocks — and when to failover.
7. **Dashboard MVP scope**: Minimal stack (FastAPI + simple HTML/JS? or static files?) that can be replaced later by Koda PWA; data sources = SQLite (extend key_tracker DB?) vs new DB.

### Research plan (multi-round, deep)
- **Round 1:** Map the current “DeepSeek Flash V4.1 FREE” offering: official DeepSeek naming, where “Flash V4.1” appears, NVIDIA NIM catalog/pages, OpenRouter entries, any other aggregators. Capture exact model IDs and endpoints.
- **Round 2:** For each viable free provider, collect rate limit/quota docs, header names, error shapes, reset semantics, and whether any programmatic quota endpoint exists.
- **Round 3:** KiloCode integration: how custom OpenAI-compatible providers / routers are configured; what fields Kilo expects (base URL, model id). Determine feasible integration path for “RedFox Router: DeepSeek Flash V4.1 FREE”.
- **Round 4:** Architecture options for router + telemetry store + health checks + dashboard API; propose concrete v0 backend design (files, tables, services) consistent with existing RedFox/Koda patterns (Python, httpx, SQLite/JSONL as noted in global instructions).
- **Round 5:** Risk register + open questions list for Danny + concrete next implementation steps (back-end first).

(Each round: research → summarize findings here → list what’s still unknown → decide next round focus.)


---

## 2026-11-15 — Research Round 1 (model identity, provider landscape, “FREE” variants)

### What “DeepSeek Flash V4.1 FREE” likely refers to (working hypothesis)
The phrase is used informally. We need to be precise because naming differs by provider:

- **NVIDIA NIM (integrate.api.nvidia.com, free tier for developers)**: commonly referenced as `deepseek-ai/deepseek-v4.1-flash` (see horizonlux.com, freellm.net, MadRobot). Free tier claims: up to **40 RPM, 10,000 requests/day** (per several sources; some say “limits may vary / throttled by traffic”). OpenAI-compatible base `https://integrate.api.nvidia.com/v1`. Trial terms: testing/eval only, prompts/outputs may be used for NVIDIA product improvement on free tier, endpoints can be deprecated/retired. **This is the NVIDIA key we already track** (key tracker entry: “NVIDIA NIM (deepseek-v4.1-flash, nemotron-3-ultra)”, free tier).
- **AMD Radeon Cloud Token Factory**: serves **DeepSeek-V4-Flash** (build 0731 in some writeups), OpenAI + Anthropic at `https://developer.amd.com.cn/radeon/api/v1`. Documented limits (from china-ai-arbitrage writeup): **30 RPM/key, 8 concurrent/key, 20 RPM/account gateway** (sliding 60s), plus **daily spend cap** (example $10/day, resets Asia/Shanghai). Exposes `X-RateLimit-*` headers and 429s include `Retry-After` plus codes like `token_rate_limit_exceeded`, `model_concurrency_rate_limit_exceeded`. Also mentions usage endpoint like `GET https://radeon-global.anruicloud.com/api/profile/model-usage?include_recent=true` (auth’d). China-addressed console; free/shared tier, quotas can vary per account.
- **OpenCode Zen**: model id seen in issues/code snippets as `deepseek-v4-flash-free` (and branded “DeepSeek V4.1 Flash Free”). Access is contentious: outside-OpenCode calls reported as **403 FreeTierError** (“only usable from within OpenCode”) by Apidog test; separate GitHub issue reports `429 FreeUsageLimitError` even via certain paths and notes **User-Agent gating** for `-free` models on Zen gateway behavior in that context (must send `User-Agent: opencode/...` for some cases) — but even then, “free tier can only be used from within OpenCode” was reported as a hard block in that test. Also personal daily allowance style limits mentioned elsewhere in Zen/rate-limit docs snippets (e.g., teamorouter page showed `deepseek-v4-flash-free` 200 req/day in some table context?) — but sources are mixed/conflicting across forks/docs. **Not a clean programmatic BYOK router target** for arbitrary clients; high operational risk.
- **OpenRouter**: lists models like `deepseek/deepseek-v4-flash` (paid-ish in snippet shown: $0.09/$0.18 per 1M in that page) and also has `:free` variants ecosystem-wide, but the specific “Flash V4.1 FREE” string needs confirmation. Snippet showed limits notes like “Free: 50/day if credits<10 etc.” for that model id on one page — but that may be a different versioning/naming than “V4.1”. Needs deeper check.
- **Official DeepSeek API (api.deepseek.com)**: docs show `deepseek-flash` as the served model name for that tier now (points to DeepSeek-V4.1-Flash-1017 in note shown) with OpenAI/Anthropic-compatible base URLs. Third-party pages mention “Free 60 RPM / 100K TPM” tier on some DeepSeek-hosted free plans (deepseek.day snippet) — but this is the **official platform free tier** (account-based), not the same as “NVIDIA free tier” keys. Different billing/quota system.

### Key observations relevant to “router that rotates keys/providers when limits hit”
1. **There is no single universal “DeepSeek Flash V4.1 FREE” API**; it’s a capability offered by multiple providers under different model IDs, different auth, different quota semantics, and different ToS (some disallow production). A “router” must treat each as a distinct backend with its own adapter.
2. **NVIDIA NIM (current broken key context)**: published free limits often cited as **40 RPM, 10,000 RPD** (daily). However, multiple sources say “limits may vary by model and other users’ traffic can cause throttling”, “free endpoints retired often”, and trial ToS restrict to testing/eval. Also forum thread shows someone asking to increase from 40→200 RPM — suggests limits are enforced server-side; we do not have public evidence of rich quota headers like `x-ratelimit-remaining-requests` being guaranteed across all NIM free endpoints in the same way as some commercial APIs. This is a critical gap for “remaining requests/tokens + reset time remaining”.
3. **AMD Token Factory** is one of the clearest for observability signals in docs: returns `X-RateLimit-*` and 429 with `Retry-After` + error codes; also has a **usage endpoint** (`/api/profile/model-usage`) that can report daily spend/caps (example $10/day). That’s promising if we add AMD as a backend later — but geo/ToS/signup friction noted.
4. **OpenCode Zen free path is a poor fit** for a general router (client-gated / ToS constraints reported). Probably not a target for “use in KiloCode via our router” unless we explicitly decide otherwise.
5. **Quota visibility is provider-dependent** (the hardest part of your ask): some give headers, some give only 429 + Retry-After, some give a dashboard/API endpoint, some give nothing usable. The router/telemetry design must assume **partial observability** and fall back to **client-side rate accounting + adaptive backoff + health scoring**.

### Open questions carried into Round 2
- For NVIDIA NIM (`integrate.api.nvidia.com`, model `deepseek-ai/deepseek-v4.1-flash`): what headers are actually returned on success and on 429? Does it ever return `x-ratelimit-*`, `retry-after`, `x-request-id`, usage hints? Need to test with a real key (careful: free tier ToS says testing/eval; also may log prompts). Alternatively, search for observed headers in community posts/repos.
- Exact current status of NVIDIA free endpoint for that model id (is it still “free endpoint” in practice, or deprecated like the 0731 build page suggested for that specific slug?). The user says key “currently not working” — could be quota exhausted, could be temporary outage, could be endpoint changes.
- For any provider we might support, define a normalized “quota snapshot” schema that can represent: known limits (from config/docs), observed headers, inferred counters, reset times (absolute + countdown), and confidence level.
- KiloCode integration: how does a user point KiloCode at a “custom router” and see a custom model name like “RedFox Router: DeepSeek Flash V4.1 FREE”? Need to research KiloCode provider config mechanics.


---

## 2026-11-15 — Research Round 2 (observed behavior, quotas/headers patterns, KiloCode integration, architecture sketch)

### Live checks (local, using NVIDIA_API_KEY from env)
- `GET https://integrate.api.nvidia.com/v1/models` with Bearer key: **HTTP 200**, model list includes `deepseek-ai/deepseek-v4.1-flash` (present in catalog at time of check).
- `POST https://integrate.api.nvidia.com/v1/chat/completions` for `deepseek-ai/deepseek-v4.1-flash` (small prompt, `max_tokens=8`, non-stream): **times out / no HTTP response in practice** (observed `curl` exit 28 after ~30s, reported HTTP 000 in that attempt). This matches prior note in `~/.config/opencode/opencode.jsonc`: “Do NOT use the NVIDIA free route for this model; the edge proxy drops the connection before the first byte (HTTP 000)”. So current “not working” is consistent with that observed failure mode (not a simple 429 in this test).
- Same call for `nvidia/nemotron-3-ultra-550b-a55b`: **HTTP 200** (returned a completion with reasoning tokens). Confirms key/auth and endpoint reachability for other models.

### NVIDIA NIM (free tier) — what we can say from sources + observation
- Commonly cited limits (horizonlux/freellm/MadRobot): **~40 RPM, 10,000 requests/day** for free endpoints on build.nvidia.com (NVIDIA Developer Program). “Limits may vary by model and other users’ traffic can cause throttling.” Free tier is **trial/testing/eval oriented** (ToS), prompts/outputs may be used for improvement on free tier, and free endpoints/models can be retired. No guaranteed public standard quota headers surfaced clearly in the snippets I found; community reports suggest throttling occurs but exact header contract is not well-documented in those pages.
- Observed: the specific model `deepseek-ai/deepseek-v4.1-flash` is listed but **not reliably callable** in practice right now (connection drop) — could be deprecation/disabled route, temporary incident, or policy change. This is exactly the kind of “upstream issue” the router must detect and log.

### AMD Token Factory (DeepSeek-V4-Flash family) — stronger observability signals (from writeups)
- OpenAI + Anthropic compatible at `https://developer.amd.com.cn/radeon/api/v1`. Documented layers: **30 RPM/key, 8 concurrent/key, 20 RPM/account gateway (60s sliding)**, plus **daily spend cap** (example $10/day, resets Asia/Shanghai). Responses carry **`X-RateLimit-*`** headers (including user-daily-USD remaining mentioned) and **429** returns **`Retry-After`** plus codes like `token_rate_limit_exceeded`, `model_concurrency_rate_limit_exceeded`. Also mentions a **usage endpoint**: `GET https://radeon-global.anruicloud.com/api/profile/model-usage?include_recent=true` (Bearer). This is the most “instrumentable” free-ish option among what we reviewed (if you can obtain access / tolerate geo/ToS constraints).
- Not the same model string as NVIDIA’s `deepseek-ai/deepseek-v4.1-flash` in all cases (AMD shows `DeepSeek-V4-Flash` / build variants in writeups) — naming/availability must be verified per account.

### OpenCode Zen `deepseek-v4-flash-free`
- Mixed reports: some paths require special `User-Agent` behavior in certain gateway contexts (GitHub issue), but other reports say **free tier only usable from within OpenCode app** (403 FreeTierError when called externally). Also rate-limit stories vary (some say daily allowances like 200/day in some docs, others report persistent 429s). **Not recommended as a backend for an external “RedFox Router”** due to client gating and instability signals.

### OpenRouter
- Paid model pages show `deepseek/deepseek-v4-flash` (different naming from “V4.1 Flash FREE”) with posted rate notes on some pages (e.g., free-tier request limits depending on credits) — but not a clean match to “DeepSeek Flash V4.1 FREE” as commonly phrased. Requires targeted lookup per exact desired model id.

### Official DeepSeek API (api.deepseek.com)
- Official docs: OpenAI/Anthropic compatible, `model: "deepseek-flash"` served as DeepSeek-V4.1-Flash-1017 (per docs snippet). This is **paid account** in practice for normal use? (deepseek.day snippet mentioned free tier 60 RPM/100K TPM on some pages, but official billing terms vary; need to be careful.) Not “free tier keys” in the NVIDIA/AMD free-program sense unless explicitly on a free plan — probably out of scope for “FREE” focus except as a paid fallback later.


### KiloCode / “custom router” integration notes (from docs)
From Kilo docs (OpenAI-Compatible providers, Custom Models): you can add a **custom OpenAI-compatible provider** in Settings/`kilo.json`. Key points:
- Provider API options include **OpenAI Compatible** (Chat Completions style) for generic endpoints; you set `baseURL`, optional `apiKey`, and define `models` (or auto-fetch from `/v1/models` if supported). Also supports full endpoint URLs in some flows.
- Model entries need `name`, `limit.context/output` (important; missing limits disables compaction/usage tracking in practice). `tool_call`, `reasoning`, etc. can be set.
- For a “router” that fronts multiple upstreams, the cleanest integration is usually: run a local HTTP service that exposes an **OpenAI Chat Completions-compatible** API (and ideally `/v1/models`) so Kilo can treat it like a custom OpenAI-compatible provider. Then in Kilo you’d configure a custom provider pointing at that local URL and list models like `redfox-router/deepseek-flash-v41-free` (or whatever naming you choose). That matches how other proxies/routers are typically consumed.
- Alternative: if the router is “just” another provider config pattern, but more realistically a router is a gateway service you stand up (FastAPI/uvicorn) implementing `/v1/chat/completions`, `/v1/models`, plus health/quota endpoints for your dashboard.
- **Important constraint from docs**: `{env:...}` resolution rules in config are strict in some contexts (project-level config may not resolve env refs in the same way) — but for a local service you control, easier to have the service read keys from env/keychain/server config. For Kilo side, pointing to `http://127.0.0.1:PORT/v1` with no API key is fine if you don’t enforce one locally.

### What “model name shown in KiloCode” could look like (design intent)
User wants: when selected, show something like **“RedFox Router: DeepSeek Flash V4.1 FREE”**. Practically:
- In Kilo, create a custom provider (e.g. ID `redfox-router`) with base URL `http://localhost:<port>/v1` (OpenAI Compatible).
- Define a model in that provider, e.g. key `deepseek-flash-v41-free`, display name `RedFox Router: DeepSeek Flash V4.1 FREE` (so the picker shows that). The router maps this logical model to the best available upstream backend(s) for that capability.

This is a presentation/UX choice in Kilo config; the router’s job is to route that logical id.


---

## 2026-11-15 — Research Round 3 (observability reality, failure/health semantics, data model options, architecture proposal)

### Provider observability matrix (what we learned)
**NVIDIA NIM (build.nvidia.com / integrate.api.nvidia.com), model `deepseek-ai/deepseek-v4.1-flash` (free/trial tier context)**
- Observed: model appears in `/v1/models` (200). A chat completion attempt timed out / yielded no HTTP response in our quick test (curl timeout) — consistent with known “edge/proxy drops connection” note in local OpenCode config. Also community reports of throttling behavior that can feel stricter than stated; some tools/proxies (e.g. community rate-limiter projects, forum posts) treat free tier as effectively ~40 RPM in practice and warn about 429s/backoff complexity. NVIDIA forums threads note: no standard `Retry-After`/`X-RateLimit-*` documented in some cases; people implement client-side heuristics.
- Implication for telemetry: **cannot rely on provider quota headers** for this backend today. Must track: request outcomes (success/timeout/connection drop/4xx/5xx), latency, 429 frequency, last error signature, rolling client-side counters (per key, per model) with configurable assumed windows (e.g. assume 40 RPM / 10k RPD as *policy hints* from docs, not truth). “Remaining requests” is **estimated** unless/until we discover real headers.
- Health detection: classify failures into buckets (e.g. `auth_error`, `rate_limited`, `upstream_timeout_or_drop`, `model_unavailable`, `server_error`, `unknown`) and compute a health score / circuit-breaker state per (provider, model, key) with cooldowns.

**AMD Radeon Cloud Token Factory (DeepSeek-V4-Flash family)**
- Strongest observed signals in official docs: `X-RateLimit-Limit/Remaining/Reset-User-RPM`, `X-RateLimit-Limit/Used/Remaining/Reset-User-Daily-USD` on responses; 429 returns `Retry-After` and structured errors with codes (`token_rate_limit_exceeded`, concurrency variants, gateway `rate_limit_exceeded` / daily cap messages). Usage endpoint: `GET /api/v1/usage?include_recent=...` (or as documented) returns daily/period totals, `daily_cost_limit/used/remaining_usd`, reset times (Asia/Shanghai). Also console mentions `GET /api/profile/model-usage` in some contexts — but API docs page describes `GET /v1/usage` behavior in the usage section text we captured conceptually; need to be precise during implementation (verify against live docs/behavior).
- Implication: this backend can populate a **high-confidence quota snapshot** (remaining daily “points”, RPM remaining if headers present on last call, reset timestamps). This is the best model for what the dashboard should eventually show when a provider supports it.
- Caveats: geo (China site), ToS/availability, model naming varies, and “USD” fields are points (not money) — but still useful as capacity units.

**OpenCode Zen (`deepseek-v4-flash-free`)**
- Reported client-gating (free tier only inside OpenCode app in some tests), and mixed rate-limit behavior in issues. Not a practical external backend for a general router you control; exclude from v0 backend roster unless Danny explicitly wants to experiment (and accept fragility).

**Others (OpenRouter paid/free variants, official DeepSeek paid API)**
- Not “FREE” in the NVIDIA/AMD free-program sense for the stated goal; out of scope for v0 focus except as future fallbacks if desired.

### Failure classification (proposed)
Normalize upstream outcomes into a small enum for logging + routing decisions:
- `ok`
- `auth` (401/403 with auth meaning)
- `rate_limit` (429) — parse `Retry-After`, error codes if present
- `quota_exhausted` (daily cap / no remaining) — if detectable
- `timeout` (client timeout, network timeout)
- `connection_dropped` (empty/000, TLS/reset patterns) — important for NVIDIA observed case
- `model_unavailable` (404/model not found, endpoint deprecated)
- `upstream_5xx` / `upstream_error`
- `invalid_request` (4xx other, bad payload) — should not trigger failover blindly except config fixes
Router policy (v0, conservative): prefer failover on `rate_limit`, `quota_exhausted`, `timeout`, `connection_dropped`, `upstream_5xx`, `model_unavailable` only if we know alternative backends can serve the **same logical capability** (same “DeepSeek Flash V4.1 FREE” intent) — but today that capability is split across providers with different model IDs and different terms; the “router” v0 should be honest about this mapping.

### Data model direction (extend vs new)
Current `key_tracker` (SQLite, `~/.claude/data/api_keys.db`) already tracks key metadata + expiry/reminders. Options:
- **Option A (extend in place):** add tables/columns for usage snapshots, request events/logs, provider health state. Pros: one DB, key records already exist (e.g. NVIDIA NIM entry id=6). Cons: key_tracker.py is currently CLI-focused on expiry; mixing concerns can bloat it, but pragmatic for v0.
- **Option B (new DB/service store):** e.g. `~/.claude/data/redfox_router.db` (or under `redfox-router` project). Pros: clean separation, easier schema evolution. Cons: need to link keys (by stable id or by project/provider/identifier). Key tracker already has ids.

Recommendation (v0): **start with a new SQLite DB owned by the router project** (e.g. `~/.local/share/redfox-router/router.db` or `~/Documents/projects/redfox-router/data/router.db` — pick a clear location and document it). Reason: router needs high-volume event/snapshot tables (requests, quota_snapshots, incidents) that differ from expiry reminders; keep `key_tracker` as the “secret/key registry” source of truth for key existence/expiry, and reference keys by `(project, provider, identifier)` or store a foreign key string. Alternatively, add tables into the same DB file but via a new module — also fine if we want to share the file; but easier to version separately. I’ll propose a concrete choice in the architecture section below.

### Dashboard MVP (barebones) — proposed scope
- Backend: FastAPI (Python, consistent with many RedFox/Koda helpers using httpx; global instructions mention Python 3.11+, httpx async). Serve a small SPA/static page or just server-rendered HTML for v0.
- Views/panels (v0):
  - **Providers/backends** table: name, logical capability (“DeepSeek Flash V4.1 FREE”), upstream model id, base URL, auth source (key ref), enabled/disabled, current health state, last check time, last error summary.
  - **Keys**: list from registry (read-only link) + router-specific usage snapshots (remaining RPM/day estimates or provider-reported values when available, reset countdowns).
  - **Recent incidents/events**: last N failures with timestamps, provider, error class, message snippet (sanitized), retry-after if known.
  - **Live/refresh**: simple polling (e.g. every 10–30s) is fine for barebones.
- No auth required initially if bound to localhost; document later.

### KiloCode integration path (practical v0)
- Run router as a local service at `http://127.0.0.1:PORT/v1` implementing OpenAI Chat Completions (`POST /v1/chat/completions`) and ideally `GET /v1/models`.
- In Kilo, add a custom OpenAI-compatible provider pointing to that base URL, add a model with display name **“RedFox Router: DeepSeek Flash V4.1 FREE”** (logical id like `deepseek-flash-v41-free`). Router selects backend(s) in priority order, applies rate/health policies, fails over on configured failure classes, logs incidents.
- v0 reality check: only backends that can actually serve that capability are viable. Given today’s observations, **NVIDIA’s `deepseek-ai/deepseek-v4.1-flash` is currently problematic/unreliable**; AMD is a strong candidate if we can onboard it (separate account/setup). So v0 may need to be honest: support the logical model but report “no healthy backend available” with diagnostics until a working backend is configured. That’s still useful infrastructure.


---

## 2026-11-15 — Research Round 4 (concrete v0 architecture proposal, aligned with existing patterns)

### Principles (from global instructions + your constraints)
- Back-end first; dashboard barebones now, replaceable later by “RedFox Team style / Koda PWA”.
- Python 3.11+, `httpx` async preferred for HTTP clients (matches many helpers). SQLite for state; JSONL acceptable for append-only logs if useful. Keys from macOS Keychain/env patterns consistent with existing helpers (do not hardcode secrets). Never run heavy compute on Mac — this is lightweight API/router work.
- Build over buy; no markup/wrapper services. Self-hosted router.

### Proposed repo layout (under `~/Documents/projects/redfox-router/`)
```
redfox-router/
  README.md
  BUILD_LOG.md
  docs/
  src/
    redfox_router/
      __init__.py
      config.py            # load config (YAML/TOML/JSON) from env or file
      models.py            # Pydantic/dataclasses: Backends, Keys, QuotaSnapshot, Incident
      store/
        db.py              # SQLite init/migrations (router.db)
        repo.py            # CRUD for backends, keys-ref, snapshots, incidents, request_log
      backends/
        base.py            # BackendAdapter interface: chat(), list_models(), fetch_quota(), health_probe()
        nvidia_nim.py      # NVIDIA NIM (OpenAI-compat) adapter
        amd_token_factory.py  # stub later if/when added
        openai_compat.py   # generic OpenAI-compatible adapter helper
      router/
        policy.py          # backend selection, failover rules, cooldowns/circuit state
        engine.py          # route logical model -> try backends in order
      observability/
        classifier.py      # map HTTP/exception -> FailureClass
        quota.py           # normalize headers/usage endpoints into QuotaSnapshot
        incidents.py       # write structured incidents
      api/
        server.py          # FastAPI app: /v1/chat/completions, /v1/models, /health
        dashboard.py       # minimal HTML/JSON endpoints for dashboard
      dashboard_static/    # barebones HTML/CSS/JS (polling)
  scripts/
    dev_server.py          # or `python -m redfox_router.api.server`
  pyproject.toml (or requirements.txt)
```
This is a proposal; can be simplified for v0 (fewer files) if preferred, but structure helps growth.

### Logical model naming (v0 focus)
- Logical model id exposed by router (Kilo-facing): `deepseek-flash-v41-free` (example) with display name **“RedFox Router: DeepSeek Flash V4.1 FREE”**.
- Backends map this logical id to provider-specific upstream ids (e.g. NVIDIA: `deepseek-ai/deepseek-v4.1-flash`; AMD: TBD per account/model name). Mapping lives in config.

### Database (router store) — suggested tables (SQLite)
Separate DB file, e.g. `router.db` in a known data dir (documented). Suggested tables:
- `backends` (id, name, kind, base_url, upstream_model_id, enabled, priority/order, auth_ref, notes, created_at, updated_at)
- `api_keys` (optional mirror) OR reference external key_tracker by `(project, provider, identifier)`. Prefer referencing key_tracker IDs/keys conceptually but storing router’s own key material refs carefully: **do not store secrets in router.db**; store references like env var name or keychain service name + identifier, and resolve at runtime.
- `quota_snapshots` (id, backend_id, observed_at, source: headers|usage_api|inferred, rpm_limit, rpm_remaining, rpm_reset_at, daily_limit_units, daily_used_units, daily_remaining_units, daily_reset_at, raw_json, confidence: high|medium|low)
- `request_events` (id, ts, backend_id, logical_model, http_status, failure_class, latency_ms, retry_after_s, error_excerpt_sanitized, prompt_tokens_est, completion_tokens_est, notes)
- `incidents` (id, opened_at, closed_at, backend_id, severity, failure_class, summary, details_json)
- `backend_health` (backend_id, state: healthy|degraded|down|cooldown, last_ok_at, last_error_at, consecutive_failures, cooldown_until, updated_at)

This supports: dashboard showing status/remaining/reset when known, recent incidents, and health-driven routing.

### Routing/failover policy (v0)
- For a request to logical `deepseek-flash-v41-free`, iterate enabled backends in priority order (configurable).
- Skip backends in `cooldown` or `down` unless cooldown expired and probe says OK (or always try with backoff rules).
- On failure classes: `rate_limit` → record `Retry-After` if present, set cooldown (respect header or policy default), try next backend if policy allows multi-backend failover. `quota_exhausted` → mark backend exhausted until reset time. `timeout`/`connection_dropped`/`upstream_5xx`/`model_unavailable` (context-dependent) → increment failures, apply short cooldown, try next backend. `auth` → mark down, do not hammer, alert via incident.
- Always log the attempt chain and final outcome (for dashboard + debugging).
- **Important honesty rule**: if only one backend is configured and it fails, return a clear error to client (OpenAI-style error body) and record incident; do not silently pretend success.

### Upstream auth strategy
- NVIDIA NIM: Bearer token from env (e.g. `NVIDIA_API_KEY`) or keychain lookup (helper pattern) — same as current local usage.
- AMD: Bearer token / headers per their docs (`Authorization: Bearer rc-...` or `x-api-key` for some endpoints) — configure via env/secret ref.
- Router reads secrets at runtime from a config file that references env vars (e.g. `${NVIDIA_API_KEY}`) to avoid committing secrets.

### Observability & “remaining requests/tokens, reset time remaining”
- **Passive capture**: on every response/429/error, parse headers (`Retry-After`, any `x-ratelimit-*` if present) and store in `quota_snapshots` / `request_events`.
- **Active polling (optional, v0.5+)**: for AMD, call usage endpoint periodically to get `daily_cost_remaining_usd` (points), `daily_reset_at`, etc., and store snapshots. For NVIDIA, no known usage API — so show “unknown / estimate only” based on client counters + assumed limits (configurable), clearly labeled in UI.
- Dashboard shows: “Remaining (reported by provider)”, “Reset in …”, “Confidence: high/medium/low”, “Last observed …”.

### KiloCode integration (concrete steps once router runs)
1. Start router: `uvicorn redfox_router.api.server:app --host 127.0.0.1 --port 8787` (example port).
2. In Kilo settings (or `kilo.json`), add custom OpenAI-compatible provider, base URL `http://127.0.0.1:8787/v1`, no API key needed locally (or set one if you add auth later).
3. Add model entry: id/key `deepseek-flash-v41-free`, display name `RedFox Router: DeepSeek Flash V4.1 FREE`, set `limit.context`/`limit.output` appropriately (conservative defaults until confirmed; e.g. context 200k–1M depending on backend reality — better to be accurate, but easier to start with a safe number and refine).
4. Select that model in Kilo.

### Risks / open items (carry forward)
- NVIDIA `deepseek-ai/deepseek-v4.1-flash` currently not reliably callable from this environment (timeout/connection drop observed). Router must treat this as a real backend that may be down/unavailable; dashboard should show it clearly. May need to deprioritize or remove until NVIDIA fixes/restores.
- “DeepSeek Flash V4.1 FREE” exact upstream mapping differs by provider (NVIDIA id vs AMD naming). Config must be explicit.
- AMD requires account/access (China site context in docs) — adding it is a separate setup step (credentials, base URL, model id). Not blocked by code design, blocked by access.
- No universal quota headers from all providers → UI must be honest about estimates vs reported data.
- ToS: NVIDIA free tier is trial/eval; AMD terms vary. Router should be used responsibly (internal/testing focus per your stated current use? You said “using the DeepSeek Flash V4.1 FREE models here” in Kilo context — document constraints).


---

## 2026-11-15 — Research Round 5 (synthesis, decisions, next implementation steps)

### Summary: what we know (high confidence)
- **Key registry exists** and is working: `~/.claude/helpers/key_tracker.py`, DB `~/.claude/data/api_keys.db`. You have an active NVIDIA NIM entry (id=6, notes mention `deepseek-v4.1-flash, nemotron-3-ultra`, free tier). No stored secrets there (by design) — NVIDIA key is in `~/.zshrc` as `NVIDIA_API_KEY` (also referenced in OpenCode config).
- **NVIDIA NIM**: `GET /v1/models` returns `deepseek-ai/deepseek-v4.1-flash` in the catalog (confirmed now). A direct chat call to that model timed out/no response in our test (matches your note in OpenCode config about connection drop). In contrast, `nvidia/nemotron-3-ultra-550b-a55b` worked (200). Published free-tier guidance (various sources): ~40 RPM / 10k RPD for some free endpoints, trial/eval ToS, throttling can be worse in practice, and **no reliable public quota headers documented** in the sources we reviewed; community tooling often assumes 40 RPM and uses heuristics/backoff.
- **AMD Radeon Cloud Token Factory** is the clearest for observability among free options we reviewed: documented `X-RateLimit-*` (RPM + daily USD/points remaining/reset), 429 `Retry-After` + error codes, and a usage endpoint (`/v1/usage` per docs we captured) returning daily/period stats and resets (Asia/Shanghai). Requires AMD account/setup (China-addressed console noted). Model naming differs from NVIDIA’s exact string.
- **KiloCode custom integration**: easiest path is a local **OpenAI Chat Completions-compatible** service (`/v1/chat/completions`, ideally `/v1/models`) configured as a custom OpenAI-compatible provider in Kilo; define a model with your chosen display name (e.g. “RedFox Router: DeepSeek Flash V4.1 FREE”). Do not rely on project-level `{env:...}` tricks in odd places; run the router locally and manage secrets in router env/keychain.

### Summary: what’s unknown / risky
- Whether NVIDIA will restore/fix `deepseek-ai/deepseek-v4.1-flash` free endpoint access (current failure looks like edge/proxy drop). Could be temporary or permanent change.
- Exact real-time headers/limits NVIDIA returns on success/429 for the models that do work vs this one (we didn’t capture meaningful headers on the failing call). Need targeted probe if model becomes reachable again.
- Whether any “free” backend other than NVIDIA/AMD can credibly serve “DeepSeek Flash V4.1 FREE” with acceptable terms for your use — OpenCode Zen is problematic for external router use; OpenRouter official free variants have different naming/constraints.
- AMD onboarding details for Danny (account, key, exact model id for the Flash V4 family) — not done here.

### Proposed v0 scope (agreed direction)
1. **New project**: `~/Documents/projects/redfox-router/` (done: README, BUILD_LOG). 
2. **Backend-first**: implement a minimal router service (FastAPI) that:
   - Exposes OpenAI-compatible `GET /v1/models` and `POST /v1/chat/completions` for a single logical model: `deepseek-flash-v41-free` (“RedFox Router: DeepSeek Flash V4.1 FREE”).
   - Supports **NVIDIA NIM backend first** (adapter using `https://integrate.api.nvidia.com/v1`, upstream model `deepseek-ai/deepseek-v4.1-flash`) with robust error classification, timeouts, retries/backoff policy, and incident logging — **even if currently unhealthy**, so the system records and surfaces the issue (your requirement: detect upstream issues, log them, show on dashboard).
   - Stores events/quota snapshots/health/incidents in a dedicated SQLite DB (proposed `router.db` under project `data/` or XDG-style path; document choice).
   - Provides minimal JSON/HTML dashboard endpoints + a barebones static page showing: backend status, last error/incident, request counts (client-side), and any observed headers/reset hints (with confidence labels). No fancy UI yet.
3. **Key/usage tracking extension**: integrate conceptually with existing `key_tracker` (reference NVIDIA key entry) but implement router telemetry separately (as above). “Track remaining usage on each key and when usage resets”: v0 implements **passive capture + inferred counters + config-based assumed limits** for NVIDIA (labeled estimates) and the schema to ingest **provider-reported** data for AMD later (and for any backend that exposes it). Full provider-reported polling can be v0.1 if time allows; v0 should at least have the data model and display placeholders clearly.
4. **KiloCode config example** documented in repo (custom OpenAI-compatible provider pointing to local router).

### Concrete next steps (implementation plan I can start executing)
- Step A: scaffold `redfox-router` Python package (`pyproject.toml` or `requirements.txt`, `src/redfox_router/...`) with config loading (env vars for secrets: `NVIDIA_API_KEY`, optional AMD keys later).
- Step B: implement SQLite store + migrations for tables listed in Round 4.
- Step C: implement NVIDIA NIM OpenAI-compatible adapter (httpx async) + failure classifier + request logging + health/cooldown state.
- Step D: implement router engine for logical model `deepseek-flash-v41-free` (single backend chain for now) + FastAPI app with `/v1/models`, `/v1/chat/completions`, `/health`, `/api/status` (JSON), and a minimal `index.html` dashboard.
- Step E: write docs in `docs/` (setup, running, KiloCode config, known limitations about NVIDIA current state) and update BUILD_LOG with implementation entries.
- Step F: manual smoke test against NVIDIA (expect failure logged/surfaced given current behavior) and verify dashboard shows incident/status.

### Questions for you (only if you want to steer now; otherwise I can proceed with reasonable defaults)
1. **Backend priority for v0**: confirm we start with NVIDIA only (even if broken) + prepare AMD as “disabled/configurable later”? (I recommend yes.)
2. **Router DB location**: prefer `~/Documents/projects/redfox-router/data/router.db` (repo-local, easy to back up) or `~/.local/share/redfox-router/router.db` (XDG-style, out of repo)? I lean repo-local under `data/` but can do either.
3. **Local auth for the router API**: none for localhost v0, or add a simple shared secret header? I recommend none for v0.
4. **Assumed NVIDIA limits for UI estimates** (until real data): default to **40 RPM, 10,000 RPD** (common published numbers) with clear “estimated” labels? I recommend yes, configurable in config.

If you don’t answer, I’ll proceed with defaults: NVIDIA-only v0, repo-local `data/router.db`, no local auth, assumed 40/10k with “estimated” labeling.

---

## 2026-11-15 — Key registry + Kilo config updates (rdfx2 + Koda)

### Key tracker entries added (`~/.claude/helpers/key_tracker.py`, DB `~/.claude/data/api_keys.db`)
All added as `expires=never`, metadata only (no secrets stored). Notes call out free-only and rdfx2 scope where relevant.

**rdfx2 (Kilocode)**
- id 10: ZRO / `primary (rdfx2 kilocode)` — free-only, no expiry. User provided key `sk-1b0o…7m4A` (configured in Kilo `~/.config/kilo/kilo.jsonc` under provider `zro`, base `https://zro.moonmath.ai/v1`).
- id 13: Routeway / `primary (rdfx2 kilocode, free only)`. Key `sk-TTrhjz…qxIh` → Kilo provider `routeway`, base `https://api.routeway.ai/v1`.
- id 11: TokenHarbor / `primary (rdfx2 kilocode, free only)`. Key `thk_live_ogGe…wJHu` → Kilo provider `tokenharbor`, base `https://tokenharbor.ai/v1`.
- id 12: Orcarouter / `primary (rdfx2 kilocode, free only)`. Key `sk-orca-3llxa…pO5k6` → Kilo provider `orcarouter`, base `https://api.orcarouter.ai/v1`.

**rdfx2 (OpenCode)**
- id 14: ZRO / `primary (rdfx2 opencode, free only)` — free-only, no expiry (tracked; not written into Kilo config in this step).

**Koda system** (keys provided for Koda; need separate config wiring in Koda side when ready)
- id 15: Routeway / `koda primary (free only)` — `sk-iXZpw…OtQ`. Notes: free-only; quota sharing vs other Routeway keys to be tested/researched.
- id 16: TokenHarbor / `koda primary (free only)` — `thk_live_1qIF6…wqSI`. Quota sharing to be tested/researched.
- id 17: BlazeAPI / `koda primary (free only, ~1 req/min noted)` — `blaze-5d8e…e21`. Notes mention ~1 req/min; treat as constrained; quota sharing TBD.
- id 18: Orcarouter / `koda primary (free only)` — `sk-orca-rM988…hcJ`. Quota sharing TBD.
- id 19: BeatAPI / `koda primary (free only, ~1 req/min)` — `sk-BfNSi…8u`. ~1 req/min per user note; route smartly.

### Kilo config (`~/.config/kilo/kilo.jsonc`)
Added OpenAI-compatible custom providers (validated by Kilo config validation after edit): `zro`, `routeway`, `tokenharbor`, `orcarouter`. Keys are embedded in that file per current setup (note: global instruction warns about `{env:...}` resolution rules in some contexts; for now keys are literal in this local config). Models lists left minimal/empty where provider catalogs are large/fetched dynamically by clients in practice — can be refined later.

### Open research/testing needed (quota sharing: Koda vs Kilocode per provider)
User asked to research and test whether request limits/quotas are shared between Koda and Kilocode keys for the same provider, or independent per key. Recorded as follow-up:
- For each provider (Routeway, TokenHarbor, Orcarouter, BlazeAPI, BeatAPI, Zro, etc.), determine: is quota enforced per API key, per account/org, per IP, or per billing unit? Document from official docs and validate with controlled tests (e.g. send requests from “Koda context” key vs “Kilocode context” key in parallel/sequence and observe 429s/quota headers/balances).
- BeatAPI and BlazeAPI notes indicate very low/constrainted limits (~1 req/min mentioned for BeatAPI); design router/Koda routing to be quota-aware and conservative.
- This is a research task to be scheduled/executed (can be a dedicated doc section in redfox-router or a separate notes file) before building cross-system routing that assumes independence.


---

## 2026-11-15 — Docs added: quota/limits testing plan + handoff notes

### New documentation
- `docs/quota-limits-testing-plan.md` — draft plan to determine per-key vs account/org/IP/shared quota for providers used by rdfx2 (Kilocode/OpenCode) and Koda. Includes provider/key inventory (from tracker), test matrix (A/B/C/D), headers to capture, constrained-provider cautions (BeatAPI ~1 req/min, BlazeAPI noted), results table template, and open questions (BlazeAPI/BeatAPI endpoints not yet fully documented).

### Handoff: “read this to continue with no prior context”
If you are a new agent/session picking up RedFox Router work, read in this order:
1. `README.md` (project goals, v0 focus: DeepSeek Flash V4.1 FREE, back-end first, barebones dashboard now).
2. This file, `BUILD_LOG.md` (full chronological research rounds + decisions + key registry/config changes + this handoff section).
3. `docs/quota-limits-testing-plan.md` (quota testing plan for multi-key/multi-system usage).

**What is done (so far):**
- Project scaffolded at `~/Documents/projects/redfox-router/` with README + BUILD_LOG + `docs/quota-limits-testing-plan.md`.
- API key registry extended (`~/.claude/helpers/key_tracker.py`, DB `~/.claude/data/api_keys.db`) with entries for rdfx2 (Kilocode/OpenCode) and Koda (Routeway, TokenHarbor, Orcarouter, BlazeAPI, BeatAPI). All `expires=never`, metadata only. See “2026-11-15 — Key registry…” section above for IDs/labels/notes.
- Kilo local config updated: `~/.config/kilo/kilo.jsonc` now includes OpenAI-compatible providers `zro`, `routeway`, `tokenharbor`, `orcarouter` (keys embedded locally in that file). Config validated by Kilo tooling after edit.
- Research completed (5 rounds in BUILD_LOG): DeepSeek Flash V4.1 FREE naming/provider landscape, observed NVIDIA NIM behavior (model listed but chat to `deepseek-ai/deepseek-v4.1-flash` timed out/connection drop in tests; `nvidia/nemotron-3-ultra-550b-a55b` worked), AMD observability strengths, KiloCode custom provider integration path, v0 architecture proposal (FastAPI + SQLite router store + adapters + classifier + dashboard MVP), synthesis and proposed defaults.

**What is NOT done yet (next concrete work):**
- Implement RedFox Router service (scaffold Python package, `router.db`, NVIDIA adapter, classifier, FastAPI `/v1/models` + `/v1/chat/completions` for logical model `deepseek-flash-v41-free`, minimal dashboard endpoints/page). Defaults proposed: repo-local `data/router.db`, no localhost auth, NVIDIA-only v0 even if unhealthy (log/surface), assumed 40 RPM/10k RPD labeled “estimated”.
- Add AMD backend adapter/config path later (after account/setup).
- Run quota/limits tests per `docs/quota-limits-testing-plan.md` (especially Routeway/TokenHarbor/Orcarouter pairs, BeatAPI/BlazeAPI careful tests, Zro key10 vs key14).
- Wire Koda system keys into Koda’s own config/routing (separate from Kilo’s `kilo.jsonc`). Document where Koda reads keys.
- Revisit NVIDIA `deepseek-ai/deepseek-v4.1-flash` reachability periodically; if fixed, validate headers/behavior and update router.

**Key file locations (quick reference):**
- This project: `~/Documents/projects/redfox-router/` (README.md, BUILD_LOG.md, docs/).
- Key tracker helper: `~/.claude/helpers/key_tracker.py` (CLI). DB: `~/.claude/data/api_keys.db`.
- Kilo config (macOS): `~/.config/kilo/kilo.jsonc` (providers added here). Global instructions: `~/.config/kilo/AGENTS.md`, master refs in `~/.claude/REFERENCES.md`.
- NVIDIA key env (local shell): `NVIDIA_API_KEY` in `~/.zshrc` (used by OpenCode/NVIDIA examples). Router should read from env/keychain refs, not hardcode.

**Decisions/defaults recorded (unless you change them):**
- v0 backend focus: NVIDIA NIM first (`deepseek-ai/deepseek-v4.1-flash`) as logical backend target even if currently failing (for observability/logging), with AMD planned later.
- Logical Kilo-facing model name intent: “RedFox Router: DeepSeek Flash V4.1 FREE” mapped to logical id `deepseek-flash-v41-free` (to be implemented).
- Router DB preferred: `~/Documents/projects/redfox-router/data/router.db` (repo-local) unless changed.
- No local auth for router in v0 (localhost). Assumed NVIDIA limits 40 RPM / 10,000 RPD shown as estimated until provider-reported data exists.

**How to verify Kilo shows new providers after relaunch:**
- Open Kilo (IDE/CLI as you use it). In Providers/model settings, look for custom/OpenAI-compatible providers named: `zro`, `routeway`, `tokenharbor`, `orcarouter` (names come from `provider` keys in `kilo.jsonc`). If models aren’t listed, that can be normal if the provider doesn’t expose `/v1/models` in a way Kilo auto-fetches or if you left models empty; you can still add models manually in Kilo UI or extend `kilo.jsonc` under each provider’s `models` map. The important part is the **provider entries exist** in config (they do now).


---

## 2026-11-15 — v0 SERVICE IMPLEMENTED (`src/redfox_router`)

Backend-first v0 is built and running, following the Round 4 architecture. No frontend framework; a
barebones dashboard is included.

### What shipped

```
src/redfox_router/
  secrets.py      resolve key: env var first, then Keychain (claude-vault.<slug>)
  config.py       backends + logical models + assumed limits
  classifier.py   HTTP/exception -> failure enum (ok|auth|rate_limit|quota_exhausted|
                  timeout|connection_dropped|model_unavailable|upstream_5xx|invalid_request)
  store.py        sqlite: request_events, backend_health, quota_snapshots, incidents
  engine.py       route a logical model across its backend chain, failover, record telemetry
  server.py       FastAPI: /v1/models, /v1/chat/completions (stream + non-stream),
                  /health, /api/status, / (dashboard)
  dashboard.html  status/quota/incidents/events, 5s poll
tests/test_router.py   8/8 (no network: httpx MockTransport)
scripts/install_service.py  -> launchd com.daniel.redfox-router on 127.0.0.1:8787
run.sh, requirements.txt
```

**Backends (verified working Koda free routes, 2026-11-15):** `tokenharbor`, `beatapi`, `routeway`.
Keys resolve from the environment first, then macOS Keychain. **Logical models:**
`deepseek-flash-v41-free` (tokenharbor -> beatapi) and `gemma-4-26b-free` (routeway).

### Live verification

- `deepseek-flash-v41-free` -> `tokenharbor`, HTTP 200, content returned.
- `gemma-4-26b-free` -> `routeway`, HTTP 200; Routeway's `x-ratelimit-*` captured
  (rpm 4/5, rpd 190/200, reset seconds) into `quota_snapshots`.
- **Failover proven live:** forced `tokenharbor` into cooldown, next call returned
  `x-redfox-backend: beatapi` with HTTP 200; cooldown cleared afterwards.
- `GET /` dashboard 200; `/api/status` shows per-backend health, latest quota snapshot, incidents.

### Integrated with the Mac daemon (consumer side)

`opencode.jsonc` gained a `redfox-router` provider (`http://127.0.0.1:8787/v1`), and the Mac daemon's
800B model is now `redfox-router/deepseek-flash-v41-free`. A live 800B outbox task traversed the router
end to end; the router logged `deepseek-flash-v41-free -> tokenharbor ok 1720ms`. This is the payoff:
the daemon no longer hardcodes a provider, so the next upstream failure is rotation + a dashboard
incident, not a broken task.

### Open items

- BeatAPI returns a `usage.quota.percent` in the response body; the router currently captures only
  `x-ratelimit-*` headers, so that signal is not yet recorded. Enhancement: parse `usage.quota`.
- No auth on the router API (localhost-only bound; fine for v0).
- The streaming path is implemented but has not yet been exercised by a streaming client.
- v0 routes non-stream by default; verify with a real streaming consumer before relying on it.
