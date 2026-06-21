# Leg: merge-queue-parent-id-comment

**Status**: ready
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Merge the duplicated `QUEUE_PARENT_ID` audit comment in `playlists.py` so the `parent_id != "-1"` firmware invariant is stated once (finding I-11).

## Context
- Maintenance report 2026-06-02, finding **I-11** (Advisory, Documentation / redundant comment) — the maintainer's comments priority axis.
- `playlists.py:33-40` states the `parent_id != "-1"` firmware invariant **twice** in one comment block: lines ~34-37 ("Must NOT be -1... 'A:TRACKS' is the conventional...") then lines ~37-39 repeat it as a "NOTE: Flight 1 hardware finding — parent_id='-1' loses track titles... any non-'-1' value preserves them".
- Both statements are correct and match `CLAUDE.md:118-128`; the value `"A:TRACKS"` matches usage at `playlists.py:370`. This is a redundant comment, not a wrong one.

## Inputs
- `playlists.py` with the duplicated comment block around lines 33-40

## Outputs
- One consolidated comment block stating the invariant + the Flight-1 audit-trail pointer once.

## Acceptance Criteria
- [ ] The `parent_id != "-1"` invariant is stated once in the `QUEUE_PARENT_ID` comment block (no repeated paragraph)
- [ ] The merged comment retains both pieces of information: the rule (`parent_id != "-1"`, `"A:TRACKS"` conventional) AND the Flight-1 hardware-finding audit-trail pointer
- [ ] `QUEUE_PARENT_ID = "A:TRACKS"` value and its usage at `playlists.py:370` are unchanged
- [ ] No code change (comment only)

## Verification Steps
- Read `playlists.py:33-40` → one coherent comment block, no duplicated paragraph
- `grep -n "A:TRACKS" mcp_sonos/playlists.py` → value/usage unchanged
- `pytest` → unchanged (sanity; comment-only)

## Implementation Guidance

1. **Merge the two paragraphs** — combine into a single block: state the rule
   (`parent_id` must not be `"-1"`; `"A:TRACKS"` is the conventional value) and
   keep the audit-trail pointer (Flight 1 hardware finding: `"-1"` loses titles,
   any non-`"-1"` preserves them).
   - **Design-review correction:** the current comment does NOT cite
     `CLAUDE.md` — do NOT add a `CLAUDE.md:NNN` line reference (it would
     introduce a line number that drifts). Just merge the two existing paragraphs.

## Edge Cases
- **Keep the audit trail** — do not drop the "Flight 1 hardware finding"
  provenance; merge it in, don't delete it. The provenance is the comment's value.

## Files Affected
- `mcp_sonos/playlists.py` - merge the `QUEUE_PARENT_ID` comment block

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing (N/A — comment only)
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
