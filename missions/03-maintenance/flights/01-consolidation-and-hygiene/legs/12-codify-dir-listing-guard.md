# Leg: codify-dir-listing-guard

**Status**: completed
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Codify the `audio_host.py` directory-listing-disabled guard in `CLAUDE.md` "When extending" so future contributors preserve it (finding I-12).

## Context
- Maintenance report 2026-06-02, finding **I-12** (Advisory, Documentation) — a Mission-01 carry-forward (flagged in the Flight-01 and Flight-02 debriefs of the baseline mission), still open.
- `audio_host.py:78-80` overrides `list_directory` to return 404 — disabling directory listing on the LAN-public audio host. This is a security-relevant invariant (part of the F2/F9 threat-model boundary) but is NOT documented in `CLAUDE.md` "When extending", unlike the now-codified supply-chain and eager-parse idioms.
- Risk: a future contributor refactoring `audio_host.py` could re-enable directory listing without realizing it's a deliberate guard.

## Inputs
- `mcp_sonos/audio_host.py` with the `list_directory` 404 override (lines ~78-80)
- `CLAUDE.md` with the "When extending" section (already contains the supply-chain + eager-parse idioms)

## Outputs
- A short entry in `CLAUDE.md` "When extending" documenting that the audio host disables directory listing on purpose and that this guard must be preserved.

## Acceptance Criteria
- [ ] `CLAUDE.md` "When extending" documents the directory-listing-disabled guard: what it is (`list_directory` → 404 in `audio_host.py`), why (the audio host binds LAN-public/unauthenticated; listing would expose the staged-file directory), and that it must be preserved on any `audio_host` refactor
- [ ] The entry sits alongside the existing codified idioms (supply-chain, eager-parse) in the same section
- [ ] No code change

## Verification Steps
- `grep -n "directory listing\|list_directory" CLAUDE.md` → the guard is now documented
- Read the "When extending" section → the entry is consistent in tone/format with the existing codified idioms
- Confirm `audio_host.py:78-80` still has the guard (the doc must describe reality)

## Implementation Guidance

1. **Add the entry** — in `CLAUDE.md` "When extending", add a short bullet/
   paragraph: the audio host (`audio_host.py`) disables directory listing
   (`list_directory` → 404) because it binds `0.0.0.0` unauthenticated on the LAN
   (firewall-scoped, accepted threat model); any refactor of the handler must keep
   listing disabled so the staged-file directory isn't enumerable.
   - Match the describe-don't-prescribe tone of the existing codified idioms.

## Edge Cases
- **Describe reality** — confirm the guard is still at `audio_host.py:78-80`
  before documenting it (it is, per this cycle's inspection). The doc must match
  the code.

## Files Affected
- `CLAUDE.md` - add the directory-listing-guard entry to "When extending"

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow (flight-end review + single commit). Do not commit; mark the leg `landed` and signal `[LAND:leg]`.

## Citation Audit (Flight Director, 2026-09-26 resume)
- `mcp_sonos/audio_host.py:78-80` — `def list_directory(self, path):  # block GET / enumeration` → `self.send_error(404)`; guard present (confirmed 2026-09-26). Binds `("0.0.0.0", self.port)` at line 82. Current CLAUDE.md "When extending" codified idioms: cross-cutting input validation, eager-parse env vars — add alongside those.
