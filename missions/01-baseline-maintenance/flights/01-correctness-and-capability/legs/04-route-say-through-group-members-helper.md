# Leg: 04-route-say-through-group-members-helper

**Status**: ready
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
Replace the inline `coord.group.members` access in `controller.py:309-314` with a call through `_group_members_of`, preserving the CLAUDE.md invariant that "every method that touches `speaker.group.coordinator` or `speaker.group.members` must go through these" (Finding F5 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `controller.py:309-314` is inside `say()`. It uses an inline `try/except` around `coord.group.members` to guard against the transient `None` state that occurs after rapid group dissolves.
- This is functionally equivalent to `_group_members_of` today, but violates the stated invariant. Any future contributor who reads `controller.py` top-down sees one pattern in `_group_members_of` and another inline at line 309-314; they may copy the inline pattern when adding new methods, reintroducing the `AttributeError: NoneType ...` crashes the helper was created to prevent.
- `_group_members_of` returns member *names* (strings), not SoCo objects. `say()` needs SoCo objects (for join/transport calls), so either: (a) call `_group_members_of` and then `_resolve(name)` for each, or (b) extend `_group_members_of` to optionally return SoCo objects.

## Inputs
- `mcp_sonos/controller.py:309-314` inline `coord.group.members` access in `say()`
- Existing `_group_members_of(speaker)` helper

## Outputs
- `say()` accesses group membership through `_group_members_of` (possibly with a `_resolve`-name-to-speaker hop)
- Same external behavior

## Acceptance Criteria
- [ ] `controller.py` has no inline `.group.members` access outside `_group_members_of`
- [ ] `say(target="all", ...)` still works against live hardware
- [ ] `say(target="<single speaker>", ...)` still works
- [ ] Grep audit: `grep -n "\.group\.members" mcp_sonos/controller.py` returns hits only inside `_group_members_of`'s definition

## Verification Steps
- `grep -n "\.group\.members" mcp_sonos/controller.py` → only one hit (inside `_group_members_of`).
- Manual: `say("all", "test")` works.
- Manual: `say("Kitchen", "test")` works.
- `smoke_test.py` passes (covers `say` via the `Sonos says hello` line).

## Implementation Guidance

1. **Read** the current block at `controller.py:309-314`. Architect's finding cites a try/except around `coord.group.members`. Confirm the actual shape before editing.

2. **Refactor option A (preferred)**: Call `_group_members_of(coord)` to get names, then `[self._resolve(n) for n in member_names]` to get SoCo objects:
   ```python
   member_names = self._group_members_of(coord)
   members = [self._resolve(n) for n in member_names]
   ```

3. **Refactor option B**: Extend `_group_members_of` with an optional `return_speakers=False` parameter that returns SoCo objects when True. Only do this if the resolve hop in option A turns out to repeat across multiple call sites.

4. **Sanity check** the rest of `controller.py` for other inline group/coordinator accesses that should also be routed through the helpers — Inspector reported only the one in `say()`, but a fresh grep catches any drift since the report was written.

## Files Affected
- `mcp_sonos/controller.py` — `say()` method (and possibly `_group_members_of` if option B)

## Edge Cases
- **Empty group / coordinator alone**: `_group_members_of` should already handle this. Verify it returns `[coord.player_name]` or equivalent so `say` still hits the coordinator.
- **`_resolve` raises if name not found**: that's a real error (speaker disappeared mid-call). Don't swallow.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes (covers `say`)
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
