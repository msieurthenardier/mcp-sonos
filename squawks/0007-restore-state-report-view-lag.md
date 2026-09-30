# Squawk 0007: `targeting_smoke.py restore-state` match report reads a lagging per-speaker view

**Status**: open
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: —

## Report
`restore-state` can report a speaker as `matched:false` and exit 1 even
though the restore succeeded. Its verification read samples each speaker's
group once, through that speaker's own topology view, immediately after the
joins. That view can lag by a moment.

Observed in behavior-test run
[2026-09-29-05-02-18](../tests/behavior/target-set-playback/runs/2026-09-29-05-02-18.md),
step 12: Patio was reported with `group_members` [Fireplace Room, Lounge,
Patio], missing Dining Room. A topology read immediately afterwards showed
full convergence. A rerun passed.

## Evidence
- `targeting_smoke.py:cmd_restore_state`: the final per-speaker report reads
  group membership once, with no settle-poll.
- `topology` and `stop-all` in the same file already sync and read through
  each coordinator's own view (M04 F02 leg 04). `restore-state`'s report was
  not given the same treatment.
- Fix is obvious: poll the verification read, clearing the cache and
  re-reading, until it matches or a short cap of about 3 s runs out, before
  declaring a mismatch. This is apparatus-only, and it can be verified
  against the `FakeHousehold` lag mode.

## Corrective Action
*(written at completion)*

## Verification

## Sign-Off
*(written at completion)*

## Disposition
