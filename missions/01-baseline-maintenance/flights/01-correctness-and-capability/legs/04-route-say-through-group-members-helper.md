# Leg: 04-route-say-through-group-members-helper

**Status**: completed
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
Replace the inline `coord.group.members` access inside `say()` (the `if volume is not None:` block) with a call through `_group_members_of`, preserving the CLAUDE.md invariant that "every method that touches `speaker.group.coordinator` or `speaker.group.members` must go through these" (Finding F5 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

> Note on line numbers: Leg 02 added `import os` and new init/play_file content to `controller.py`, shifting all `say()` line numbers down by ~12. The block to replace is identifiable by description (inside `say()`, inside the `if volume is not None:` branch) — verify by reading current code rather than relying on a specific line number citation in this leg.

## Context
- Inside `say()`, the inline block uses `try/except` around `coord.group.members` to guard against the transient `None` state that occurs after rapid group dissolves.
- This is functionally equivalent to `_group_members_of` today, but violates the stated invariant. Any future contributor who reads `controller.py` top-down sees one pattern in `_group_members_of` and another inline; they may copy the inline pattern when adding new methods, reintroducing the `AttributeError: NoneType ...` crashes the helper was created to prevent.
- `_group_members_of` returns member *names* (strings), not SoCo objects. `say()` needs SoCo objects (for setting volume on each member), so either: (a) call `_group_members_of` and then `_resolve(name)` for each, or (b) extend `_group_members_of` to optionally return SoCo objects. **This leg uses option (a)**; option (b) is out of scope (only one call site needs objects).

## Inputs
- `mcp_sonos/controller.py:309-314` inline `coord.group.members` access in `say()`
- Existing `_group_members_of(speaker)` helper

## Outputs
- `say()` accesses group membership through `_group_members_of` (possibly with a `_resolve`-name-to-speaker hop)
- Same external behavior

## Acceptance Criteria
- [x] `controller.py` has no inline `.group.members` access outside `_group_members_of`
- [x] `say(target="all", ...)` still works against live hardware
- [x] `say(target="<single speaker>", ...)` still works
- [x] Grep audit: `grep -n "\.group\.members" mcp_sonos/controller.py` returns exactly **one** hit, inside `_group_members_of`'s definition body (2 line-hits — both inside the helper body)
- [x] `or [coord]` fallback dropped (provably unreachable — `_group_members_of` always returns a non-empty list, falling back to `[speaker.player_name]` in the failure case); this simplification is intentional, not an accidental loss

## Verification Steps
- **Before editing**: `grep -n "\.group\.members" mcp_sonos/controller.py` → expect 2 hits (helper definition + inline access in `say`).
- **After editing**: `grep -n "\.group\.members" mcp_sonos/controller.py` → exactly 1 hit (helper only).
- Manual: `say("all", "test")` works against live hardware.
- Manual: `say("Kitchen", "test")` works.
- `smoke_test.py` passes (covers `say` via the `Sonos says hello` line).

## Implementation Guidance

1. **Read** the current `say()` method to confirm the shape (line numbers shifted by Leg 02 — find the block by description: inside `say()`, inside `if volume is not None:`).

2. **Replace the inline block** with the helper-driven equivalent:
   ```python
   if volume is not None:
       member_names = self._group_members_of(coord)
       members = [self._resolve(n) for n in member_names]
       for m in members:
           m.volume = volume
   ```
   Notes:
   - `_group_members_of(coord)` guarantees a non-empty list — falls back to `[coord.player_name]` (line 69) when `coord.group.members` raises or is empty.
   - Drop the `or [coord]` fallback — it's now provably unreachable. Don't carry it as belt-and-suspenders; the helper IS the contract.
   - `self._resolve(name)` looks up the SoCo in the cached speakers list. In theory a stale cache could return a different SoCo than the original `coord`; in practice the 30s TTL plus the just-resolved coordinator at the top of `say()` makes this effectively impossible.

3. **Sanity check**: `grep -n "\.group\.coordinator\|\.group\.members" mcp_sonos/controller.py` after the edit — should show only matches inside the two helpers (`_coordinator_of` at line ~45 and `_group_members_of` at line ~63). Inspector reported only `say()` drifts; verify no other site quietly drifted since the report.

4. **Out of scope**: extending `_group_members_of` to return SoCo objects (option B). Only one call site needs objects; option A keeps the helper's contract single-purpose.

## Files Affected
- `mcp_sonos/controller.py` — `say()` method (and possibly `_group_members_of` if option B)

## Edge Cases
- **Empty group / coordinator alone**: `_group_members_of` should already handle this. Verify it returns `[coord.player_name]` or equivalent so `say` still hits the coordinator.
- **`_resolve` raises if name not found**: that's a real error (speaker disappeared mid-call). Don't swallow.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Smoke test passes (covers `say`)
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
