# Leg: reword-tool-count-comment

**Status**: ready
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Reword the `CLAUDE.md` "the other 31 tools" phrasing so it no longer reads as drift against the three "32 tools" assertions (finding I-9).

## Context
- Maintenance report 2026-06-02, finding **I-9** (Advisory, Documentation / redundant-or-incorrect comment) — the maintainer's comments priority axis.
- `CLAUDE.md:240` says "the other 31 tools keep working" (in the `play_file`-disabled rationale), while three other places assert 32 tools (`CLAUDE.md:8`, `server.py:49` docstring, `README.md:437`).
- The "31" is arithmetically *intentional* (32 minus the disabled `play_file`) but reads like a stale count next to the "32" assertions — a drift hazard for a future reader.

## Inputs
- `CLAUDE.md` with the "31 tools" phrasing around line 240

## Outputs
- The sentence reworded to avoid the bare number (e.g. "the remaining tools keep working") so no count can drift.

## Acceptance Criteria
- [ ] `CLAUDE.md` no longer contains "31 tools" (or the bare "31" in that sentence); the phrasing conveys "all tools except the disabled `play_file`" without a number
- [ ] The three "32 tools" assertions are unchanged and remain accurate (the count is verifiable via `grep -c "@mcp.tool" mcp_sonos/server.py` = 32)
- [ ] No code change

## Verification Steps
- `grep -n "31" CLAUDE.md` → the "31 tools" phrasing is gone
- `grep -rn "32" CLAUDE.md README.md mcp_sonos/server.py` → the 32-tool assertions remain
- `grep -c "@mcp.tool" mcp_sonos/server.py` → 32 (confirms the assertions are still correct)

## Implementation Guidance

1. **Reword** — change "the other 31 tools keep working" to "the remaining tools
   keep working" (or equivalent). The point is to drop the number that looks like
   drift, not to change the meaning.

## Edge Cases
- **Do not "correct" 31 → 32** — that would be wrong (the sentence is about the
  set with `play_file` disabled). Remove the number instead.

## Files Affected
- `CLAUDE.md` - reword the `play_file`-disabled rationale sentence

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing (N/A — docs only)
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
