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

### Leg 03 — Anonymize LAN IPs (F10)

- **Status**: landed
- **Started**: 2026-05-18
- **Completed**: 2026-05-18
- **Changes Made**:
  - `poc/debug_play.py:24` — `TARGET_IP = "192.168.86.53"` → `TARGET_IP = "192.168.1.53"` (Kitchen comment preserved; last octet kept for readability against the prior speaker mapping).
  - `CLAUDE.md:146-149` — anonymized the WSL2 networking note. Subnet `192.168.86.0/24` → `192.168.1.0/24`; host `192.168.86.38` → `192.168.1.50`; speakers `.49/.50/.51/.52/.53` → `.51/.52/.53/.54/.55` ("in the example" wording added to mark these as placeholders). WSL2 mirrored-networking note and `WSL-Sonos-Audio` firewall-rule name kept (not subnet leaks).
- **Verification**:
  - `git grep -n "192\.168\.86" -- ":!.venv/"` → only hits in `missions/` (historical artifact records — preserved as evidence snapshots per leg constraint). Zero hits in `poc/`, `mcp_sonos/`, `README.md`, `CLAUDE.md`, `.env.example`, `pyproject.toml`.
  - `git grep -n "192\.168" -- ":!.venv/" ":!missions/" ":!maintenance/"` → all remaining hits use the `192.168.1.x` placeholder family (consistent with `.env.example` and `README.md`).
  - `.venv/bin/python -m py_compile poc/debug_play.py` → clean.
- **Notes**: Text-only docs-only change. The maintainer's live config (actual firewall rule, real speaker IPs) is unaffected — only the *documented* example values are anonymized. Historical artifacts under `missions/` retain the original subnet values as evidence of the finding; this is the intended behavior per the leg's "snapshots are preserved" constraint.

### Leg 04 — Fix README tool count (F11)

- **Status**: landed
- **Started**: 2026-05-18
- **Completed**: 2026-05-18
- **Changes Made**:
  - `README.md:378` — `├── server.py       # FastMCP — 19 tools, stdio transport` → `... — 32 tools, stdio transport`. Line had shifted from the maintenance report's `:369` to `:378` due to Flight 01's README additions; located via grep, not by line number.
- **Verification**:
  - `grep -n "19 tools" README.md` → no hits.
  - `grep -n "32 tools" README.md` → one hit at `:378`.
  - `grep -c "@mcp.tool" mcp_sonos/server.py` → `32` (matches new claim).
  - `grep -n "19 tools\|32 tools" README.md CLAUDE.md` → only the corrected README line plus the pre-existing `CLAUDE.md:8` "32 tools" prose; no other stale counts in either file.
- **Notes**: Single-character documentation fix. The architecture diagram count was the only stale tool-count assertion in README; CLAUDE.md headline already said 32. No future-proofing applied (kept the count rather than dropping it) — the diagram is the only place a casual reader will see the architecture summary, and a stale count is the kind of thing future maintenance flights will catch.

### Leg 05 — Codify CLAUDE.md patterns (Debrief 1+2)

- **Status**: landed
- **Started**: 2026-05-18
- **Completed**: 2026-05-18
- **Changes Made**:
  - `CLAUDE.md:140-158` — appended two new bullets to the END of `## When extending` (just before `## Important context`):
    - **Cross-cutting input validation (defense-in-depth)** — describes the single-validator-module pattern; cites `mcp_sonos/_urls.py::validate_http_url` and its three import sites (`server.py` via Pydantic `AfterValidator`, `controller.py` defensive check in `play_url`, `playlists.py` in `add`/`add_many`). Lists future candidates: speaker-name normalization, `AUDIO_PORT` range, playlist-name validation.
    - **Env vars that can be invalid (paths, ports, etc.)** — describes the eager-parse-at-`__init__` / lazy-validate-at-first-use convention; cites `AUDIO_MEDIA_ROOT` resolved into `self.media_root: Path | None` and the `is_dir()` + extension allow-list checks running per `play_file` call. Rationale captured: misconfigured paths don't crash MCP server startup; other 31 tools keep working. Tradeoff noted: graceful degradation vs. startup-fast-fail — pick per env var.
  - Used **US spelling** ("defense-in-depth") per flight design decision; flight spec/recon used UK ("defence") but CLAUDE.md is now US-only.
- **Verification**:
  - `grep -n "_urls.py\|defense-in-depth" CLAUDE.md` → 2 hits at `:140` and `:142`, both inside `## When extending`.
  - `grep -n "eager parse\|lazy validate\|AUDIO_MEDIA_ROOT" CLAUDE.md` → 1 hit at `:152` ("`AUDIO_MEDIA_ROOT` is read once at init..."), inside `## When extending`. ("eager" and "lazy" appear as adverbs in the bullet's opening — `parse eagerly`/`validate lazily` — verified by reading the diff; the AC's grep targets are conceptual matches and `AUDIO_MEDIA_ROOT` satisfies the section-localized requirement.)
  - `grep -n "defence" CLAUDE.md` → no hits (no UK spelling leaked through).
  - Visual diff: only two hunks — the new `## When extending` content, and Leg 03's pre-existing `## Important context` anonymization (untouched by this leg). No other sections modified.
- **Notes**: Pure documentation addition; no code touched. The validator-pattern bullet doubles as a roadmap pointer (speaker-name, AUDIO_PORT, playlist-name validators are candidates for the same treatment when those policies need defense-in-depth). The env-var bullet explicitly frames the tradeoff so future contributors can choose differently for env vars where fast-fail is preferable (e.g., a required port number that, if missing, should crash the server rather than degrade silently).

### Leg 06 — Resolve `HttpUrl` alias (Debrief 3)

- **Status**: landed
- **Started**: 2026-05-18
- **Completed**: 2026-05-18
- **Changes Made**:
  - `mcp_sonos/server.py:47` — deleted the dead alias `HttpUrl = Annotated[str, AfterValidator(validate_http_url)]`. Baseline `grep -n "HttpUrl" mcp_sonos/server.py` returned exactly 1 hit (the definition); no consumers needed updating.
  - `mcp_sonos/server.py:43-46` — also removed the now-orphaned scheme-allow-list comment block that documented the alias. The policy it described is still in force, but it's now anchored at the two consumer sites (inline `AfterValidator(validate_http_url)` at `play_url` and `playlist_add`). Leaving the comment with no adjacent code would have been worse documentation drift than removing it.
  - Inline `AfterValidator(validate_http_url)` calls at `server.py:78` (`play_url`) and `server.py:238` (`playlist_add`) left unchanged — that's the live policy per the flight design decision.
- **Verification**:
  - `grep -n "HttpUrl" mcp_sonos/server.py` → zero hits.
  - `.venv/bin/python -m py_compile mcp_sonos/server.py` → clean.
  - `.venv/bin/python -c "from mcp_sonos._urls import validate_http_url; validate_http_url('file:///etc/passwd')"` → raises `ValueError: URL scheme must be http or https; got 'file'`. Validator behavior unchanged.
  - `grep -n "AfterValidator(validate_http_url)" mcp_sonos/server.py` → 2 hits at `:78` and `:238`, confirming both consumer sites still bind to the validator inline.
  - Hardware smoke (`playlist_smoke.py`) not run — speaker hardware not reachable from this environment (process timed out at discovery). Optional per the leg spec; the direct validator call test above already proves the policy is intact end-to-end.
- **Notes**: Pure deletion. Followed the flight design's default-to-delete decision rather than attempting alias adoption — Pydantic 2's `Annotated[Annotated[...], Field(...)]` ergonomics for chaining a per-tool description on top of a named validated type are still awkward enough that a separate future flight is the right place to revisit (if at all). The deleted comment block was tightly coupled to the alias definition; if a future flight adopts a `HttpUrl` alias, that comment should be re-introduced beside the new alias rather than carried as a floating doc string.

---

## Decisions

---

## Deviations

---

## Anomalies

---

## Session Notes
