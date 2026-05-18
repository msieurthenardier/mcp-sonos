# Flight Log: Documentation Cleanup

**Flight**: [Documentation Cleanup](flight.md)

## Summary
(Filled in during execution.)

---

### Flight Director Notes

**2026-05-18 — Flight start**

- Mission stayed `active` (set during Flight 01 start). Flight flipped: `ready` → `in-flight`.
- Feature branch: `flight/02-documentation-cleanup` created off `flight/01-correctness-and-capability` (commit `e40ecc0`). Stacks on Flight 01; Flight 02 PR may include or supersede Flight 01 depending on PR #1's merge order.
- Crew loaded from `.flightops/agent-crews/leg-execution.md` (Developer + Reviewer, both Sonnet; Accessibility Reviewer disabled).
- Skipping `/leg` invocation per Phase 2a — all 6 legs already designed (4 inherited from scaffold, 2 added during this flight's `/flight` planning). Going straight to design-review-via-Developer per leg.
- Commit cadence: per-leg commits, matching Flight 01's pattern.
- No pre-flight smoke baseline run — this is a documentation flight; smoke tests are noise for text-only changes. Leg 06 (HttpUrl alias delete) is the only code change and will run validator smoke as part of acceptance.

---

## Reconnaissance Report

Verified each scope item against current code at flight planning time (2026-05-18, after Flight 01 landed at `5c2d406`). Source artifacts: [`maintenance/2026-05-18.md`](../../../../maintenance/2026-05-18.md) for F4/F6/F10/F11 and [`flight-debrief.md`](../01-correctness-and-capability/flight-debrief.md) Action Items for the three carry-forwards. Verified by direct file reads and grep.

| Item | Classification | Evidence | Recommendation |
|------|----------------|----------|----------------|
| F4a — `say` docstring lies about gTTS | `confirmed-live` | `server.py:194` `description="What to say. Plain text; will be synthesized via gTTS."`; `server.py:196` `description="gTTS language code..."` | Rewrite both descriptions to name Piper and mark `lang` as deprecated/ignored. Schema unchanged. |
| F4b — `playlists.py` module docstring contradicts keying invariant | `confirmed-live` | `playlists.py:4` reads "worker thread keyed by the resolved *coordinator UID*"; actual code at `playlists.py:208` keys by `speaker.uid` per CLAUDE.md invariant | Rewrite docstring to say "speaker UID" and reference CLAUDE.md. Update `:99` inline comment too. |
| F6 — unused `Iterable` import + dead `_lock` | `confirmed-live` | `controller.py:15` `from typing import Iterable` (Iterable never referenced); `controller.py:12` `import threading`; `controller.py:98` `self._lock = threading.Lock()` (only the assignment — no acquire/release/with elsewhere in the file) | Delete both. If `import threading` becomes unused after removing `_lock`, drop that too. |
| F10 — real LAN IPs in tracked files | `confirmed-live` | `poc/debug_play.py:24` `TARGET_IP = "192.168.86.53"`; `CLAUDE.md:147` documents `192.168.86.0/24`, host `.38`, speakers `.49`-`.53` | Replace with `192.168.1.x` placeholders matching `.env.example` style. |
| F11 — README architecture diagram says "19 tools" | `confirmed-live` (line drifted) | `README.md:378` (was `:369` in maintenance report; shifted by Flight 01's README additions) `├── server.py # FastMCP — 19 tools, stdio transport`. `grep -c "@mcp.tool" server.py` = 32. | Change "19 tools" → "32 tools" or drop the count. |
| Debrief 1 — codify `_urls.py` defence-in-depth pattern in CLAUDE.md | `confirmed-live` (new addition needed) | CLAUDE.md has `## When extending` section (line 126) with bullets on group access, env vars, POC scripts, etc. — but no mention of validators or `_urls.py` despite the new module landing in Flight 01. | Append a bullet to `## When extending` describing the pattern: single validator module, imported at tool + controller + manager surfaces. |
| Debrief 2 — codify "eager parse, lazy validate" env-var convention in CLAUDE.md | `confirmed-live` (new addition needed) | CLAUDE.md `## When extending` has a "New env vars" bullet (around line 138) that points to README's Configuration table and `.env.example` — but does not describe the parse-at-init / validate-on-use pattern used for `AUDIO_MEDIA_ROOT` in Flight 01. | Extend the existing "New env vars" bullet (or append a new sub-bullet) describing the pattern. |
| Debrief 3 — `HttpUrl` alias half-adoption in `server.py` | `confirmed-live` | `server.py:47` `HttpUrl = Annotated[str, AfterValidator(validate_http_url)]` — defined but unused. `server.py:85, 245` use inline `AfterValidator(validate_http_url)` instead. | Default: delete the alias (it's dead code). If a clean adoption pattern is found during implementation, adopt fully. |

**No items retired or scoped down — all 8 confirmed-live.** Line numbers refreshed against post-Flight-01 state (`5c2d406`). The `_urls.py` defence-in-depth pattern requires *new* CLAUDE.md content (it didn't exist before Flight 01 landed); the eager-parse/lazy-validate pattern requires extension of an existing bullet.

### Additional Observations (not finding-level — affect flight design)

1. **`## When extending` is the right anchor for both CLAUDE.md additions.** Two of the existing bullets already capture extension-time guidance (group access via helpers, env-var documentation); the new patterns are the same kind of "if you're about to add X, do Y" content. Avoids section sprawl.

2. **F10 and Debrief 1+2 both touch CLAUDE.md** but at different sections — F10 in the `## Important context` user-environment block (line 147), Debrief items in `## When extending` (line 126+). Sequential within a session is fine; parallel would be fine too.

3. **Leg 06 (`HttpUrl` alias) is the only leg with non-zero runtime change** — deleting the alias removes the unused symbol; behavior of the validator at call sites stays the same. Smoke tests should pass before AND after; if they fail differently between Leg 05 (CLAUDE.md edit) and Leg 06 (alias delete), that's signal.

4. **The mission's `say()` Known Issue is out of scope for this flight.** Documentation-only flight; the bug needs a code-side maintenance spike, not a doc fix.

---

---

## Leg Progress

### Leg 01 — Fix doc traps (F4)

- **Status**: landed
- **Started**: 2026-05-18
- **Completed**: 2026-05-18
- **Changes Made**:
  - `mcp_sonos/server.py:194,196` — `say` tool `text` and `lang` Field descriptions rewritten. `text` now reads "...synthesized via Piper neural TTS." `lang` description marks the parameter Deprecated/Ignored and points at `PIPER_VOICE`. Parameter itself kept (flight design decision — schema-compatible).
  - `mcp_sonos/playlists.py:1-13` — module docstring rewritten. Replaces the false "*coordinator UID*" keying claim with the correct speaker-UID keying, explains the re-resolve-per-iteration behavior, and explicitly calls out the coordinator-UID anti-pattern with a pointer to CLAUDE.md.
  - `mcp_sonos/playlists.py:101` — inline comment `# coord_uid -> session` → `# speaker_uid -> session`.
  - `mcp_sonos/controller.py:27` — stale `# gTTS at normal speed is ~150 wpm` → `# Piper at the default rate is ~150 wpm`. `TTS_TIMEOUT_SECONDS` value unchanged.
- **Verification**:
  - `grep -rn "gTTS\|gtts" mcp_sonos/` → only `tts.py:119` (historical migration-rationale comment — acceptable per leg spec).
  - `grep -n "coord_uid\|coordinator UID" mcp_sonos/playlists.py` → only the docstring's *warning against* coordinator-UID keying remains; no `coord_uid` identifiers, no false keying claim.
  - `python -m py_compile` clean on all three files.
- **Notes**: Text-only changes. No behavior change. The `lang` Field description shift does alter the MCP tool schema text exposed to agents — that's the documentation-honesty intent of the leg. No smoke test run (documentation-only per Flight Director's pre-flight call).

### Leg 02 — Remove dead lock and import (F6)

- **Status**: landed
- **Started**: 2026-05-18
- **Completed**: 2026-05-18
- **Changes Made**:
  - `mcp_sonos/controller.py:15` — deleted `from typing import Iterable` (sole symbol on the line; no other `typing` imports).
  - `mcp_sonos/controller.py:98` — deleted `self._lock = threading.Lock()` (assignment-only; no acquire/release/with sites anywhere in the file).
  - `mcp_sonos/controller.py:12` — deleted `import threading` (no remaining `threading.` references after the lock assignment was removed).
- **Verification**:
  - `.venv/bin/python -m py_compile mcp_sonos/controller.py` → clean.
  - `grep -n "Iterable\|_lock" mcp_sonos/controller.py` → no hits.
  - `grep -n "threading" mcp_sonos/controller.py` → no hits.
  - No smoke test (per Flight Director's pre-flight call; deletions are inert).
- **Notes**: Pure deletion, ~5 lines removed across the import block and `__init__`. No behavior change — the `_lock` had no usage sites, so removing it cannot have functional impact. The misleading "controller is thread-safe" signal is now gone; if real concurrency becomes a concern, the F7 test-scaffolding work will need to model proper synchronization around `_speakers`/`_speakers_ts` rather than reviving a class-level lock. The class docstring still says "speakers cache + audio host + lock" — left in place per the leg spec's tight scope (Iterable + lock + threading); that docstring drift is a candidate for a future micro-cleanup if anyone trips on it.

---

## Decisions

---

## Deviations

---

## Anomalies

---

## Session Notes
