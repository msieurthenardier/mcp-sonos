# Leg: reword-tool-count-comment

**Status**: completed
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

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow (flight-end review + single commit). Do not commit; mark the leg `landed` and signal `[LAND:leg]`.

## Citation Audit (Flight Director, 2026-09-26 resume)
- **Drifted since authoring.** The tool count is now **35** (`grep -c '@mcp.tool' mcp_sonos/server.py` = 35; `CLAUDE.md:8` and `README.md:449` both say 35). The offending sentence is now `CLAUDE.md:242` — "the other 32 tools keep working" (in the `AUDIO_MEDIA_ROOT` eager-parse bullet of "When extending"), stale again. The fix is unchanged in intent: drop the number ("the remaining tools keep working"). Read the '31'/'32' references in the Context, Acceptance Criteria and Verification sections as '32'/'35' respectively; the criterion is simply that no bare count remains in that sentence and the 35-tool assertions stay accurate.
