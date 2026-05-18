# Leg: 04-fix-readme-tool-count

**Status**: completed
**Flight**: [Documentation Cleanup](../flight.md)

## Objective
Reconcile the README "Architecture" section's "19 tools" claim with the actual count of 32 (Finding F11 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `README.md:369` reads `server.py # FastMCP — 19 tools, stdio transport`.
- README headline (`:14`), tools table (`:18-23`), CLAUDE.md (`:9`), and `grep -c "@mcp.tool" mcp_sonos/server.py` all say 32.
- The "19 tools" almost certainly predates the playlist expansion (which adds ~13 tools per the Pre-Existing playlist commit `7901f96 Add in-memory named playlists with continuous background playback`).
- Pure documentation fix.

## Inputs
- `README.md:369`

## Outputs
- README architecture diagram says "32 tools" (or drops the count and relies on the table at `:18-23`)

## Acceptance Criteria
- [x] `README.md:369` no longer claims "19 tools" (line shifted to `:378` after Flight 01 README additions; "19 tools" gone)
- [x] Either: says "32 tools, stdio transport" (matching headline), or omits the count
- [x] No other stale tool counts elsewhere in README/CLAUDE.md (grep audit — only the one site)

## Verification Steps
- `grep -n "19 tools\|tools, stdio" README.md` returns no stale `19`.
- `grep -c "@mcp.tool" mcp_sonos/server.py` matches the README claim (if a count is still asserted).

## Implementation Guidance

1. **Edit** `README.md:369` — change `19 tools` → `32 tools` (or remove the number entirely).

2. **Audit** the rest of README and CLAUDE.md for any other tool-count assertions that might also be stale. Inspector reported only the one location, but check.

3. **Consider** future-proofing: a count of 32 will go stale again when the next tool is added. If you'd rather not maintain the count in the diagram, drop it from line 369 ("FastMCP, stdio transport"); the table at lines 18-23 is the authoritative count.

## Files Affected
- `README.md`

## Edge Cases
- None.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
