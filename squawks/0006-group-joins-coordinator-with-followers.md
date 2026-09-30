# Squawk 0006: `group` can `join()` a member that coordinates others, which firmware ignores

**Status**: completed
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: 2026-09-30

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
- `mcp_sonos/controller.py:SonosController.group`: before `m.join(coord)`,
  re-read `m`'s own topology view fresh (`self._sync_view(m)`, per the
  CLAUDE.md grouping invariant — never trust a view last polled through a
  different speaker) and, if `m` still coordinates other speakers
  (`_coordinator_of(m).uid == m.uid and len(_group_members_of(m)) > 1`),
  call `m.unjoin()` first (with the same 0.3s topology-settle pause the
  method already uses elsewhere) so the subsequent `join()` always lands
  on a standalone speaker. Matches the fix shape proposed in the report.
- Operator-approved scope addition: added one unit test,
  `test_say_target_set_survives_lagging_bystander_view` in
  `tests/test_target_group_controller.py`, covering `SonosController.say()`
  with a two-name target set under `FakeHousehold` lag mode
  (`enable_lag()` + a queued stale override on a bystander), mirroring
  `tests/test_coordinator_view_hardening.py::test_play_stream_survives_lagging_bystander_view`.
  `say()` shares `_execute_plan`/`_confirm_bystanders_stopped` with
  `play_stream()`, so this test exercises the same leg-4 fix
  (`_sync_view(c0, expect_coordinator=True)`) through `say()`'s code path.
  The test passed on the first run — no fix needed for `say()` itself, no
  design-work escalation required.

## Verification
- `timeout 180 .venv/bin/python -m pytest -q` — 174 passed (before this
  change: 172 passed; net +2 tests: the squawk-0006 regression test and
  the operator-approved `say()` lag-mode test).
- New tests:
  - `tests/test_group_coordinating_member.py::test_group_unjoins_member_that_coordinates_others_before_joining`
    — confirmed it fails without the fix (`git stash` of
    `mcp_sonos/controller.py` reproduces the reported
    `AssertionError: FakeHousehold: join() issued on 'FP', which still
    coordinates other members`), and passes with it. Also asserts
    Fireplace Room's former followers (F1, F2) stay grouped together
    under a firmware-elected delegate rather than scattering to
    standalone, per the `FakeHousehold.do_unjoin` delegation semantics.
  - `tests/test_target_group_controller.py::test_say_target_set_survives_lagging_bystander_view`
    — new, passed on first run (operator-approved scope addition; no
    change to `say()`'s retry implementation).

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review. There were two cycles. Cycle 1 confirmed all four fixes. The Flight Director then required a fix for the suite runtime regression: the 0007 tests slept for real, taking the suite from 2.9 s to 11.8 s. A fake clock was added, and cycle 2 confirmed it (177 passed, 3.7 s).
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-30` on `squawk/turnaround-2026-09-30`

## Disposition
