# Flight: Documentation Cleanup

**Status**: in-flight
**Mission**: [Baseline Maintenance](../../mission.md)

## Contributing to Criteria

**Mission success criteria (from maintenance report):**
- [ ] F4 — `say` tool docstring describes Piper accurately; `playlists.py:4` docstring matches the speaker-UID keying invariant
- [ ] F6 — Unused `Iterable` import and dead `threading.Lock` removed from `controller.py`
- [ ] F10 — `poc/debug_play.py` and `CLAUDE.md` no longer contain real LAN IPs
- [ ] F11 — README "Architecture" section reflects 32 tools

**Flight 01 debrief follow-ups (bundled here — share doc surface):**
- [ ] CLAUDE.md codifies the `_urls.py` defence-in-depth pattern (single validator, tool + controller + manager call sites)
- [ ] CLAUDE.md codifies the "eager parse at `__init__`, lazy validate at first use" env-var convention (as used for `AUDIO_MEDIA_ROOT`)
- [ ] `HttpUrl` alias in `server.py` is consistently adopted OR removed — no half-adoption (define-but-don't-use)

---

## Pre-Flight

### Objective
Pure text/metadata cleanup plus three small carry-forwards from the Flight 01 debrief. Two of the original doc fixes are doc-as-traps that actively mislead readers (the `say`/gTTS lie at the MCP tool surface, and the contradictory keying claim in `playlists.py:4`). The others are anonymization (public repo hygiene) and a `README.md` arithmetic fix. The debrief carry-forwards codify two patterns that emerged in Flight 01 (`_urls.py` defence-in-depth + eager-parse/lazy-validate) and resolve a half-adopted alias in `server.py` — all share documentation surface, so bundling them here is natural rather than spawning a separate flight.

### Open Questions
- [x] Keep or delete the `HttpUrl` alias? → Resolved in Design Decisions below: **delete** unless the implementing Developer finds a clean Pydantic 2 pattern that combines `Annotated[str, AfterValidator, Field]` without churn

### Design Decisions

**`lang` parameter on `say` tool**: Keep the parameter, mark it deprecated/ignored in the description, route through controller as ignored. Don't remove — it's a backwards-compatible no-op and pulling it changes the tool schema agents may have introspected.
- Rationale: doc-only fix is lower-risk than schema change
- Trade-off: parameter still in schema; some agents may try to set it

**LAN IP placeholders**: Use `192.168.1.0/24` family throughout to match `.env.example` style; `TARGET_IP = "192.168.1.50"` in `poc/debug_play.py`.
- Rationale: house-style consistency
- Trade-off: none

**CLAUDE.md new sections placement**: Append to the existing `## When extending` section (currently at line 126) rather than creating a new top-level section. The two new patterns are extension-time guidance (what to do when adding a new validator, what to do when adding a new env var) and fit cleanly under that heading.
- Rationale: avoid section sprawl; keep extension-time guidance co-located
- Trade-off: section grows; readers still find what they need via the section header

**`HttpUrl` alias fate — delete**: The alias was defined at `server.py:47` but both consumer tools (`play_url`, `playlist_add`) inline `AfterValidator(validate_http_url)` instead of using it, because chaining `Field(description=...)` after the alias is awkward in Pydantic 2. Commit to deletion — it's dead code today. Spiking adoption in this flight risks scope creep; if Pydantic 2 ergonomics improve later, adoption can land as a future maintenance flight.
- Rationale: dead-code removal is the lowest-entropy answer; the alias's intent (named type in schema) has been overtaken by the inline `AfterValidator` calls
- Trade-off: the schema loses a named type; agents introspecting the schema see plain `str` instead of `HttpUrl`. Acceptable — the validator runs either way

**Spelling convention**: use **"defense-in-depth"** (US spelling) consistently in `CLAUDE.md` and code comments. The flight artifact and recon report drafted in UK spelling ("defence"); reconcile to US to match project house style.
- Rationale: pre-commit the convention so Leg 05 doesn't make the micro-decision
- Trade-off: minor cleanup in the leg text itself

### Prerequisites
- [ ] None — pure docs

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [x] Prerequisites verified (none)
- [x] Validation approach defined (smoke test against live hardware to confirm no behavior change)
- [x] Legs defined

---

## In-Flight

### Technical Approach
Six edits, all text or near-text. None touch runtime behavior except Leg 06 (`HttpUrl` alias delete, which is structurally a no-op if the inline `AfterValidator` calls are preserved). Smoke tests are confirmation that nothing accidentally broke.

**Commit cadence**: one commit per leg (Flight 01 established this convention; preserve for git-bisect value).

**Smoke-test coverage during the flight**: smoke tests touch zero of these surfaces directly except Leg 06 (URL validation in `play_url`/`playlist_add`). The cleanup is mostly diff-only review territory.

### Checkpoints
- [ ] F4a: `say` tool docstring updated (gTTS → Piper, `lang` marked deprecated)
- [ ] F4b: `playlists.py:4` and `:99` updated to "speaker UID" matching code
- [ ] F6: `controller.py:15` (`Iterable`) and `:98` (`_lock`) cleaned up; `import threading` also dropped if no longer used
- [ ] F10: LAN IPs anonymized in `poc/debug_play.py:24` and `CLAUDE.md:147`
- [ ] F11: README architecture diagram updated ("19 tools" → "32 tools" at current line `:378`)
- [ ] CLAUDE.md codification: `_urls.py` defence-in-depth pattern + eager-parse/lazy-validate convention appended to `## When extending`
- [ ] `HttpUrl` alias removed (or fully adopted) at `server.py:47, 85, 245`

### Adaptation Criteria

**Divert if**:
- Removing `self._lock` reveals a place that should have been using it (none expected from inspection — the lock is genuinely abandoned). The Flight 01 reviewer also confirmed it's unused.
- `smoke_test.py` starts failing in a NEW way different from the known `say()` coordinator bug (per mission Known Issues) — halt the flight and investigate before continuing. A new failure mode while editing docs implies something more than text drift.

**Acceptable variations**:
- Wording of the docstrings can flex; the constraint is "matches behavior."
- Exact placement of new CLAUDE.md content within `## When extending` (top, bottom, or alongside the existing bullet about "Anything that touches groups must use _coordinator_of and _group_members_of")

### Legs

- [x] `01-fix-doc-traps` — F4: rewrite say tool docstring + playlists.py module docstring
- [x] `02-remove-dead-lock-and-import` — F6: drop `Iterable` and `_lock` (and `import threading` if newly unused) from `controller.py`
- [ ] `03-anonymize-lan-ips` — F10: replace real IPs with placeholders in `poc/debug_play.py` and `CLAUDE.md`
- [ ] `04-fix-readme-tool-count` — F11: README "19 tools" → "32 tools"
- [ ] `05-codify-claude-md-patterns` — Flight 01 debrief follow-up: append `_urls.py` defence-in-depth pattern + eager-parse/lazy-validate env-var convention to `## When extending` in `CLAUDE.md`
- [ ] `06-resolve-httpurl-alias` — Flight 01 debrief follow-up: delete (default) or fully adopt the `HttpUrl` alias in `server.py`

---

## Post-Flight

### Completion Checklist
- [ ] All 6 legs completed (each with its own commit)
- [ ] Smoke tests still pass (`playlist_smoke.py` at minimum; `smoke_test.py` is currently failing per the mission Known Issues `say()` bug — re-run, don't expect it to start passing from this flight)
- [ ] Maintenance report findings F4, F6, F10, F11 ticked in mission.md
- [ ] Flight log filled in (per-leg entries + final summary)
- [ ] PR opened (draft until ready)

### Verification
- Diff-only review: changes are text/metadata; no functional impact expected.
- `git grep "192.168.86"` returns no hits after F10 lands.
- `grep -c "@mcp.tool" mcp_sonos/server.py` matches the README claim (currently 32).
- `grep -n "HttpUrl" mcp_sonos/server.py` returns no hits after Leg 06 (if deleted) OR ≥3 hits all referencing the alias (if fully adopted).
- `grep -n "_urls.py\|eager parse\|lazy validate" CLAUDE.md` returns hits in the `## When extending` section after Leg 05.
