# Flight: Documentation Cleanup

**Status**: ready
**Mission**: [Baseline Maintenance](../../mission.md)

## Contributing to Criteria
- [ ] F4 — `say` tool docstring describes Piper accurately; `playlists.py:4` docstring matches the speaker-UID keying invariant
- [ ] F6 — Unused `Iterable` import and dead `threading.Lock` removed from `controller.py`
- [ ] F10 — `poc/debug_play.py` and `CLAUDE.md` no longer contain real LAN IPs
- [ ] F11 — README "Architecture" section reflects 32 tools

---

## Pre-Flight

### Objective
Pure text and metadata cleanup. Four legs, each ~5 minutes. Two of the doc fixes are doc-as-traps that actively mislead readers (the `say`/gTTS lie at the MCP tool surface, and the contradictory keying claim in `playlists.py:4`). The others are anonymization (public repo hygiene) and an arithmetic fix in the README.

### Open Questions
N/A — all changes are text edits with no design ambiguity.

### Design Decisions

**`lang` parameter on `say` tool**: Keep the parameter, mark it deprecated/ignored in the description, route through controller as ignored. Don't remove — it's a backwards-compatible no-op and pulling it changes the tool schema agents may have introspected.
- Rationale: doc-only fix is lower-risk than schema change
- Trade-off: parameter still in schema; some agents may try to set it

**LAN IP placeholders**: Use `192.168.1.0/24` family throughout to match `.env.example` style; `TARGET_IP = "192.168.1.50"` in `poc/debug_play.py`.
- Rationale: house-style consistency
- Trade-off: none

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
Four edits. None touch behavior; smoke tests are confirmation that nothing accidentally broke.

### Checkpoints
- [ ] F4a: `say` tool docstring updated (`server.py:182,184`)
- [ ] F4b: `playlists.py:4` and `:99` updated to "speaker UID" matching code
- [ ] F6: `controller.py:14` (`Iterable`) and `:94` (`_lock`) cleaned up
- [ ] F10: LAN IPs anonymized in `poc/debug_play.py:24` and `CLAUDE.md:147`
- [ ] F11: README:369 updated ("19 tools" → "32 tools")

### Adaptation Criteria

**Divert if**:
- Removing `self._lock` reveals a place that should have been using it (none expected from inspection — the lock is genuinely abandoned)

**Acceptable variations**:
- Wording of the docstrings can flex; the constraint is "matches behavior."

### Legs

- [ ] `01-fix-doc-traps` — F4: rewrite say tool docstring + playlists.py module docstring
- [ ] `02-remove-dead-lock-and-import` — F6: drop `Iterable` and `_lock` from `controller.py`
- [ ] `03-anonymize-lan-ips` — F10: replace real IPs with placeholders
- [ ] `04-fix-readme-tool-count` — F11: README "19 tools" → "32 tools"

---

## Post-Flight

### Completion Checklist
- [ ] All 4 legs completed
- [ ] Smoke tests still pass (no behavior changes intended)
- [ ] Maintenance report findings F4, F6, F10, F11 ticked in mission.md
- [ ] Flight log filled in

### Verification
- Diff-only review: changes are text/metadata; no functional impact expected.
- `git grep "192.168.86"` returns no hits after F10 lands.
- `grep -c "@mcp.tool" mcp_sonos/server.py` should match the README claim.
