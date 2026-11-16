# Quota & Limits Testing Plan (RedFox Router / rdfx2 + Koda)

**Purpose:** Determine whether request limits/quotas are enforced **per API key**, **per account/org**, **per IP**, or **per billing unit** for each provider used across **rdfx2 Kilocode** and **Koda system** keys. Produce evidence (logs/notes) so routing can be quota-aware and so we don’t accidentally assume independence when providers share quota.

**Scope (initial):** Providers listed below. Focus on “free only” / constrained notes first (BeatAPI ~1 req/min, BlazeAPI noted ~1 req/min). Expand as we add providers to the router.

**Principles:**
- Do **not** store secrets in git/docs. Reference keys by **tracker ID / label** only (e.g. “Koda Routeway id15”).
- Prefer **read-only / minimal calls** when testing (tiny prompts, low `max_tokens`).
- Record: timestamp (local + UTC), provider, base URL, key label, request outcome (HTTP status), headers captured (esp. rate-limit/quota headers), body/error snippet (sanitized), observed resets if any.
- Run tests in **isolated windows** and document timing.

---

## Providers & key inventory (from API key tracker + configs)

### rdfx2 (Kilocode) — tracked in `~/.claude/data/api_keys.db` (key_tracker)
| Tracker id | Provider | Label (identifier) | Notes |
|---|---|---|---|
| 10 | ZRO | `primary (rdfx2 kilocode)` | Free-only, no expiry. Kilo config: provider `zro`, base `https://zro.moonmath.ai/v1`, key set in `~/.config/kilo/kilo.jsonc` (literal). |
| 13 | Routeway | `primary (rdfx2 kilocode, free only)` | Kilo provider `routeway`, base `https://api.routeway.ai/v1`. |
| 11 | TokenHarbor | `primary (rdfx2 kilocode, free only)` | Kilo provider `tokenharbor`, base `https://tokenharbor.ai/v1`. |
| 12 | Orcarouter | `primary (rdfx2 kilocode, free only)` | Kilo provider `orcarouter`, base `https://api.orcarouter.ai/v1`. |

### rdfx2 (OpenCode) — tracked
| Tracker id | Provider | Label | Notes |
|---|---|---|---|
| 14 | ZRO | `primary (rdfx2 opencode, free only)` | Tracked only (no Kilo change). |

### Koda system — tracked (Koda-side wiring TBD)
| Tracker id | Provider | Label | Notes |
|---|---|---|---|
| 15 | Routeway | `koda primary (free only)` | Same provider family as id13; **test sharing vs independence**. |
| 16 | TokenHarbor | `koda primary (free only)` | Test vs id11. |
| 17 | BlazeAPI | `koda primary (free only, ~1 req/min noted)` | Constrained; treat carefully. |
| 18 | Orcarouter | `koda primary (free only)` | Test vs id12. |
| 19 | BeatAPI | `koda primary (free only, ~1 req/min)` | **~1 req/min** per user note; design routing to be conservative/smart. |

### Also relevant (existing)
- NVIDIA NIM key tracked under RedFox Software Factory (id6) — separate from this matrix but relevant to router backends.

---

## What to collect (per request)
- `provider`, `key_label`, `base_url`, `model_tested` (use cheapest/smallest viable model or a known free model).
- HTTP status code.
- **Headers** (log all; highlight): `retry-after`, any `x-ratelimit-*`, `x-ratelimit-limit-*`, `x-ratelimit-remaining-*`, `x-ratelimit-reset*`, provider-specific quota headers (e.g. AMD-style if ever applicable), `www-authenticate`, request-id headers.
- Response body snippet (first ~500 chars, redacted if it echoes secrets — should not).
- Wall time, local timezone noted.

Suggested output format: append rows to a CSV/Markdown table in this doc or a sibling `quota-test-results.md` (do not put keys in results).

---

## Test matrix (design)

### A. Per-key independence test (same provider, two keys, same client/IP context)
Goal: see if hitting limits on key A affects key B.
1. Pick provider P with ≥2 keys (Routeway: id13 + id15; TokenHarbor id11+id16; Orcarouter id12+id18).
2. Baseline: single small request with key A → success; single with key B → success.
3. Stress key A until rate-limited (429) or until observed ceiling (document method). Record headers/body.
4. Immediately test key B (same endpoint/model class) → does it succeed or also rate-limited?
   - If B succeeds: evidence suggests **per-key** (or at least not globally shared in that window) for that limit class.
   - If B fails similarly: evidence suggests **account/org/IP/shared pool** behavior.
5. Wait for `Retry-After`/reset if given; retest A and B.

### B. Cross-surface / cross-tool sanity (optional)
- Same key used from different clients (e.g. curl vs Kilo) — usually same key behavior, but note environment (different IPs rare on same machine; VPNs aside). Mostly sanity.

### C. Constrained providers (BeatAPI, BlazeAPI)
- Start with **very low** request rate (e.g. 1 request per 70–90 seconds for BeatAPI if ~1/min). Do **not** hammer.
- Confirm behavior matches user notes; capture any headers.

### D. ZRO (rdfx2)
- Test key10 (Kilocode context) and key14 (OpenCode context) separately: do they share quota? Also check docs for Zro account/key scoping (MoonMath/Zro). Base URLs per docs: `https://zro.moonmath.ai/v1` (OpenAI-compatible) etc.

---

## Provider-specific notes (to fill during research/tests)

### Routeway (`https://api.routeway.ai/v1`, OpenAI-compatible)
- Docs: routeway.ai docs indicate unified gateway; confirm whether limits are per API key, per account, or shared. Check for rate-limit headers on responses.
- Test models: pick a low-cost/free-tier model if exposed, or a small model; document model used.

### TokenHarbor (`https://tokenharbor.ai/v1`, OpenAI-compatible; also Anthropic at root per docs)
- Confirm per-key vs account quota; check headers and dashboard semantics if observable via API (probably not). Docs mention keys `thk_…`.

### Orcarouter (`https://api.orcarouter.ai/v1`)
- Keys `sk-orca-…`. Check docs/pages for quota/rate limits and headers.

### Zro (MoonMath) (`https://zro.moonmath.ai/v1`)
- Check API docs for rate limits, key scopes, spend limits (keys can have limits per docs snippet seen earlier).

### BlazeAPI
- Need base URL and API style (OpenAI-compatible?). **TODO:** document endpoint, auth, and any published limits before testing.

### BeatAPI
- Need base URL and API style. User states **~1 request/min** — treat as hard constraint in design; verify empirically carefully.

---

## Execution checklist
- [ ] For each provider, record official docs links about rate limits/quota (add URLs below).
- [ ] Create `quota-test-results.md` (or table section) and log each test run.
- [ ] Run A-matrix for Routeway, TokenHarbor, Orcarouter (have pairs).
- [ ] Run constrained tests for BeatAPI, BlazeAPI (after documenting endpoints).
- [ ] Run Zro pair test (key10 vs key14).
- [ ] Summarize conclusions: “assume shared” vs “assume per-key” per provider, with confidence level and evidence.
- [ ] Feed conclusions into router policy (RedFox Router) and into Koda routing rules.

---

## Results log (append)

| Date (local) | Provider | Key label | Model | HTTP | Key headers observed | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |

---

## Open questions
- BlazeAPI / BeatAPI: exact base URLs, auth headers, OpenAI-compatibility, published limits.
- Whether any provider shares quota across “projects” but not keys (unusual) — test empirically.
- For Koda vs Kilocode on the same machine/network: IP-based limits are unlikely to be the only factor if keys differ, but worth noting if both fail together unexpectedly.
