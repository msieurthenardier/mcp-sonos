# Squawk 0007: `targeting_smoke.py restore-state` match report reads a lagging per-speaker view

**Status**: completed
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: 2026-09-30

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
`cmd_restore_state`'s final per-speaker report read is now a settle-poll,
not a single sample. Factored the live read into a new helper,
`_read_speaker_row(s)`, which is exactly the old per-speaker read (volume,
mute, then `controller._sync_view(s)` + `_coordinator_of`/
`_group_members_of` to read group membership through `s`'s own view —
the same discipline `topology` and `stop-all` already use). The per-speaker
loop in `cmd_restore_state` now calls `_read_speaker_row` in a `while`
loop bounded by `SYNC_VIEW_TIMEOUT_SECONDS` (imported from
`mcp_sonos.controller`, the same 3.0s cap `_sync_view`'s own
`expect_coordinator=True` poll uses — no new constant introduced),
sleeping `SYNC_VIEW_POLL_INTERVAL_SECONDS` (0.1s, same source) between
attempts, and only records a `matched: false` / "unreadable after
retries" row once that cap elapses without a match. A matching read on
any iteration exits the loop immediately. `_retry_transient`'s existing
per-call retry on transient network errors is preserved unchanged, nested
inside each settle-poll attempt (`_read_speaker_row`) rather than
replaced. The always-print-the-report and
exit-non-zero-only-on-remaining-mismatch contract is unchanged — only the
per-speaker row's own read got slower/more patient.

Also updated the module docstring's leg-4 paragraph to note the new
settle-poll behavior, so it isn't undocumented for the next reader.

Files touched: `targeting_smoke.py` only. No `mcp_sonos/` changes were
needed or made — the fix is entirely in the apparatus's own read loop, per
the squawk's scope gate.

## Verification
Hardware is out of scope for this squawk (apparatus code, no speakers
available in this session). Checked by:

- Code read of the new `_read_speaker_row` helper and the settle-poll loop
  against `topology`'s and `stop-all`'s existing `_sync_view`-per-row
  pattern in the same file — same discipline, reused rather than
  duplicated.
- `python -m py_compile targeting_smoke.py` — clean.
- `targeting_smoke.py --help` — the script still imports and constructs its
  module-level `controller` without error (no network reached; `HOST_IP`
  and discovery aren't touched at import time).
- Added `tests/test_restore_state_settle.py`, two new hardware-free unit
  tests built on `tests/_fakes.py::FakeHousehold`'s opt-in lag mode (the
  same fake this project already uses for leg 4's coordinator-view-lag
  regression coverage in `tests/test_coordinator_view_hardening.py`).
  They monkeypatch `targeting_smoke`'s module-level `controller` to a
  stub `SonosController` wired to the fake household, and call
  `cmd_restore_state` directly:
  - `test_restore_state_settles_through_transient_view_lag`: queues ONE
    stale view through Patio (reporting it as still self-only, the exact
    mechanism from the step-12 hardware run) — the old single-sample read
    would report `matched: false`; the fixed settle-poll's second
    iteration reads ground truth (already converged) and the report shows
    a clean match, with no `SystemExit`.
  - `test_restore_state_still_reports_persistent_mismatch`: breaks
    Patio's `join()` permanently, so ground truth never converges —
    confirms the settle-poll's cap is real (it doesn't retry forever) and
    that a genuine restore failure still ends up reported as a mismatch
    with exit code 1, preserving the existing contract.
- `timeout 180 .venv/bin/python -m pytest -q`: **177 passed** (includes
  the 2 new tests; ≥175 expected).
- Test-speed fix (review feedback): the first cut of
  `tests/test_restore_state_settle.py` let `cmd_restore_state`'s
  settle-poll loop (and its two hardcoded 0.5s sleeps) run against real
  `time.sleep`/`time.monotonic`, taking the unit suite from ~2.9s to
  11.83s (`test_restore_state_still_reports_persistent_mismatch` alone
  was 7.01s — two speakers each spinning the full
  `SYNC_VIEW_TIMEOUT_SECONDS` cap; `test_restore_state_settles_through_transient_view_lag`
  was 1.10s). Fixed test-only, via a `fake_clock` fixture: monkeypatches
  `targeting_smoke.time.sleep`/`.monotonic` to a `_FakeClock` that only
  advances on `sleep()` calls, so the settle-poll loop still runs its
  real, full iteration count (the cap-bounded behavior is genuinely
  exercised) at zero wall-clock cost. No change to `targeting_smoke.py`
  production code. Re-verified: `timeout 180 .venv/bin/python -m pytest -q
  --durations=5` → **177 passed in 3.87s**; both settle tests' own call
  durations are under 0.005s (only pytest fixture setup shows, at
  0.03–0.04s each) — well under the ~0.1s target, suite back near its
  original ~3s baseline.

The next hardware behavior-test run of `target-set-playback` (step 12 in
particular) exercises this against real speaker view-lag.

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review. There were two cycles. Cycle 1 confirmed all four fixes. The Flight Director then required a fix for the suite runtime regression: the 0007 tests slept for real, taking the suite from 2.9 s to 11.8 s. A fake clock was added, and cycle 2 confirmed it (177 passed, 3.7 s).
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-30` on `squawk/turnaround-2026-09-30`

## Disposition
