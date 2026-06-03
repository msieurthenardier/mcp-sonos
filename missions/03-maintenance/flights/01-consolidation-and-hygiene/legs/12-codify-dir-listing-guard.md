# Leg: codify-dir-listing-guard

**Status**: ready
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

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing (N/A — docs only)
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] If final leg of flight:
  - [ ] Update flight.md status to `landed`
  - [ ] Check off flight in mission.md
- [ ] Commit all changes together (code + artifacts)
