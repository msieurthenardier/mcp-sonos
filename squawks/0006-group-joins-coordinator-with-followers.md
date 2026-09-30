# Squawk 0006: `group` can `join()` a member that coordinates others, which firmware ignores

**Status**: open
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: —

## Report
`group(coordinator, members)` calls `m.join(coord)` on each member without
checking whether that member currently coordinates other speakers.

Hardware probe, 2026-09-29, muted with state restored: a coordinator with
three followers that calls `join(Kitchen)` does **not** join Kitchen. The
firmware delegates coordination to another member, and the speaker stays in
its old group. So `group("Kitchen", ["Fireplace Room"])` silently fails to
join when Fireplace leads a group, even though the call returns. The response
shows it in `group_members`, but nothing raises.

## Evidence
- `mcp_sonos/controller.py:SonosController.group`: the member loop is
  `m = self._resolve(m_name); m.join(coord)`, with no `unjoin` for a member
  that is itself a coordinator of others.
- Probe log:
  [M04 F02 flight log](../missions/04-discovery-and-targeting/flights/02-target-set-playback/flight-log.md),
  "Hardware probe of grouping semantics" (case B).
- Fix is obvious: `unjoin()` any member that coordinates others before
  `join`. One unit test using the delegation-aware `SoCoFake` from M04 F02.

## Corrective Action
*(written at completion)*

## Verification

## Sign-Off
*(written at completion)*

## Disposition
