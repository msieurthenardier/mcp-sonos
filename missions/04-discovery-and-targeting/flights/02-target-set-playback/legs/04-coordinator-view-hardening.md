# Leg: coordinator-view-hardening

**Status**: completed
**Flight**: [Deterministic Target-Set Playback](../flight.md)

## Objective
Fix the hardware defect found by the leg 03 behavior-test run: after
regrouping, a coordinator-only call on `c0` falsely raises
`SoCoSlaveException`. Do this by making the last topology read before any
such call come from `c0`'s own view, and by adding a bounded resync-and-retry.

Harden the `targeting_smoke.py` apparatus against the same view lag and
against transient network errors. Repair the behavior-test spec's step 7
setup.

## Context
- **Run log:**
  `tests/behavior/target-set-playback/runs/2026-09-29-03-54-28.md`, which
  passed 9 of 12. Read it first.
- **Root cause**, established by a muted Flight Director reproduction with
  instrumentation, 3 trials, state restored:
  - Each Sonos speaker serves its **own**, eventually consistent,
    `ZoneGroupState` view.
  - SoCo caches whichever speaker's view it last polled, per household, for
    5 s.
  - `_execute_plan` confirms `c0`'s membership, then calls
    `_confirm_bystanders_stopped`. That function calls `_coordinator_of`
    on each bystander, which polls **through the bystander's lagging
    view**.
  - The cache then holds a view where `c0` (Patio) is still a follower:
    `Patio._is_coordinator` is cached as False, while a fresh read from
    Patio says True.
  - For the next ≤5 s, every `@only_on_master` call on `c0` raises
    `SoCoSlaveException`. That covers `play_uri`, `stop`, `play_from_queue`
    and `clear_queue`. `add_multiple_to_queue`, `join` and `unjoin` are
    *not* `@only_on_master` (verified in `soco/core.py`).
  - The response's `group_members` is also read from that stale view. In
    the reproduction it returned [Dining Room, Patio] while the real group
    was [Patio].
  - The same mechanism made the apparatus's `stop-all` silently stop
    nothing in steps 4 and 6, because `stop()` is `@only_on_master` and the
    script swallowed the exceptions.
- **Mislabeled error.** `play_stream` reports any `play_uri` failure as
  "The stream may be incompatible with this speaker model", including this
  one.
- **Transient `ENETUNREACH`.** Step 12's `restore-state` crashed on
  `[Errno 101] Network is unreachable` for one speaker, although the state
  was fully restored. This is the same WSL2 host behavior class that Flight 1
  recorded.
- **Step 7 spec defect.** The setup started a stream on Fireplace Room, so
  coordinator rule 2 chose Fireplace as `c0`. The intended "non-`c0` target
  coordinating bystanders → delegate" scenario therefore never happened.
  Step 9's shape (no playback in the setup) is the correct template.
- **Do not contact the Sonos speakers.** Leg 03 re-runs the behavior test
  after this leg is reviewed and committed.

## Inputs
- `c34d716`, plus the leg 03 run log and the flight log (uncommitted).

## Outputs
- `mcp_sonos/controller.py`
- `mcp_sonos/playlists.py`
- `tests/_fakes.py`
- Tests
- `targeting_smoke.py`
- `tests/behavior/target-set-playback.md`
- `CLAUDE.md`

## Acceptance Criteria

**Product (`controller.py`)**
- [ ] A new helper, `_sync_view(speaker, *, expect_coordinator=False)`:
  - It clears SoCo's ZGS cache once per household, then forces a poll
    **from `speaker` itself**, for example by reading `speaker.is_coordinator`.
    SoCo's `ZoneGroupState.poll(soco)` fetches the passed speaker's view.
  - With `expect_coordinator=True`, it re-polls every 0.1 s using
    `self._sleep`, capped at 3 s, until `speaker.is_coordinator` is True.
    If that never happens, it raises `GroupingError`, naming the view lag.
- [ ] In `_execute_plan`, before each planned `stop()`, call
  `_sync_view(coord)` on that coordinator. If `stop()` still raises
  `SoCoSlaveException`, resync and retry once. Only then does it become a
  `GroupingError`.
- [ ] In `_execute_plan`, **after** `_confirm_bystanders_stopped`, the final
  action before building the response is `_sync_view(c0,
  expect_coordinator=True)`. `TargetGroup.members` is read after that sync,
  from `c0`'s view.
- [ ] A helper `_on_coordinator(c0, action)` runs a coordinator-only action.
  On `SoCoSlaveException`, it runs `_sync_view(c0, expect_coordinator=True)`
  and retries **once**. Use it for:
  - the `stop` and `play_uri` calls in `play_stream`
  - `play_url`'s `play_uri`
  - the controller-side start of `playlist_play`, if any coordinator-only
    call happens before handing off to the engine
  - `say`'s existing `with_stale_coord_retry` stays as it is. Confirm it
    still works, since its `invalidate` already clears the ZGS cache.
- [ ] **`play_stream`'s attempts loop re-raises `GroupingError`
  immediately**, with `except GroupingError: raise` ahead of each broad
  `except Exception`, around both the cleanup `stop()` and `play_uri()`.
  It skips the scheme fallback. Otherwise the `RuntimeError`-subclass
  `GroupingError` would be swallowed into `last_reason`. A test asserts
  the raised **type** is `GroupingError` once the retry is exhausted.
- [ ] `play_stream` no longer labels a `SoCoSlaveException` as "may be
  incompatible". That wording is kept only for scheme rejections (714) and
  stalls to `STOPPED`. A coordinator-view failure that survives the retry
  raises `GroupingError` with an accurate message.
- [ ] **Playlist engines (`playlists.py`)**:
  - `_play_via_queue`'s `coord.clear_queue()` is wrapped in the existing
    `with_stale_coord_retry`, the same pattern already used for its
    `play_from_queue`.
  - `_worker`'s `coord.play_uri(...)` gets one stale-coordinator retry,
    through the existing helper and the manager's
    `invalidate_speakers_cache` / `resolve_coordinator` callbacks, before
    its existing "log and skip the track" fallback. A false
    `SoCoSlaveException` right after group formation no longer silently
    skips the track.
- [ ] `_grouping_error` gets **no** trailing sync. That is deliberate: a
  `GroupingError` always aborts the caller before any further
  coordinator-only call. Say so in a code comment.
- [ ] No existing assertion is weakened, and control tools are unchanged.

**Tests**
- [ ] `FakeHousehold` gains an opt-in **per-speaker view lag**. A
  configurable speaker can serve a stale view, listing the old membership
  and `c0` as a follower, for its next N polls. Polling through it
  overwrites the shared cache, which models the real mechanism.
  - `SoCoFake`'s coordinator-only methods (`play_uri`, `stop`) raise
    `SoCoSlaveException` when the cached view says `self` is not
    coordinator. This is opt-in, only when attached to a household with
    lag enabled.
- [ ] New tests:
  - Reproduce the hardware case: a target that was a follower of a
    bystander, and a bystander view that lags. `play_stream` now succeeds,
    and its `group_members` equals the real membership.
  - `_execute_plan`'s last poll is from `c0`.
  - `_on_coordinator` retries exactly once and then raises `GroupingError`.
  - A planned `stop()` on a lagging coordinator succeeds after a resync.
  - The `play_stream` error wording for a slave exception is not
    "incompatible".
- [ ] `timeout 180 .venv/bin/python -m pytest -q` passes with more than 165
  tests.

**Apparatus (`targeting_smoke.py`)**
- [ ] **All reads** of a group's state, including `topology` and the
  `stop-all` post-check, are read from **each coordinator's own view**.
  Clear the cache, then poll via that coordinator.
- [ ] `stop-all`:
  - For each coordinator, sync its view, then call `stop()`.
  - On `SoCoSlaveException` or a transient network error, retry up to 3
    times with a short backoff.
  - Collect per-coordinator errors, and never swallow them silently.
  - Afterwards, re-read every coordinator's own state. Exit non-zero, and
    list the offenders, if any group is still `PLAYING`.
  - Output includes `stopped`, `errors` and `still_playing`.
- [ ] `restore-state`, `group`, `mute-all` and `save-state` retry transient
  network errors (`OSError`, the requests `ConnectionError`,
  `SoCoUPnPException` for the transient 701) up to 3 times per call, with
  backoff. `restore-state`'s live match report is always produced; a read
  that fails after retries is reported per speaker. It exits non-zero only
  if a mismatch or unreadable speaker remains.

**Spec (`tests/behavior/target-set-playback.md`)**
- [ ] Step 7's setup drops the `stream --speakers "Fireplace Room"
  --no-detach` call. With no playback, rule 3 picks the standalone Kitchen
  as `c0`, and Fireplace becomes a non-`c0` target coordinating three
  bystanders. Step 7's expected result is otherwise unchanged. Add a note
  explaining why.
- [ ] The preconditions say the stream reachability check happens at step 2.
- [ ] Step 11 says "cannot be combined with", matching the real message.
- [ ] Add a dated revision note at the top of the spec.

**Docs**
- [ ] The CLAUDE.md grouping invariants gain: "Topology views are
  per-speaker and eventually consistent; SoCo caches whichever speaker it
  last polled. The last ZGS poll before any coordinator-only call must come
  from that coordinator's own view (`_sync_view`)."

## Verification Steps
- `timeout 180 .venv/bin/python -m pytest -q`
- `grep -n "_sync_view\|_on_coordinator" mcp_sonos/controller.py`
- `timeout 30 .venv/bin/python targeting_smoke.py --help`

Do not contact the hardware; leg 03's re-run verifies this.

## Implementation Guidance
1. **Model the lag in the fake first.** Write the failing hardware-case
   test, then fix `_execute_plan` / `_sync_view` / `_on_coordinator`.

   **Fake caching model**, an opt-in extension of `FakeHousehold` in which
   existing tests keep today's eager behavior:
   - The household keeps **ground truth**, today's membership, plus one
     **cached view**: a snapshot of `{uid: coordinator_uid}`, and a
     `valid` flag.
   - `speaker.zone_group_state.clear_cache()` sets `valid=False`, and keeps
     counting calls as today.
   - **A poll through speaker X** happens whenever X's `is_coordinator` or
     `group` is read. If the cache is invalid, the snapshot is refreshed
     from *X's view*:
     - ground truth, unless X has queued **stale overrides**, a per-speaker
       deque of snapshots
     - if it does, the next override is popped and used instead
     - either way, `valid` is set to True
   - `is_coordinator`, `group` and the membership reads used by
     `_coordinator_of` / `_group_members_of` all **read the cached
     snapshot** when lag mode is on.
   - `play_uri`, `stop`, `clear_queue` and `play_from_queue` raise
     `SoCoSlaveException` when the cached snapshot says `self` is not a
     coordinator, in lag mode only.
   - Tests enable lag mode and queue one stale override on the bystander
     (Dining Room) that lists Patio as its follower. That reproduces the
     hardware trace.
2. **`_sync_view` must poll from the given speaker.** Accessing
   `speaker.is_coordinator` after clearing the cache does this, because it
   calls `self.zone_group_state.poll(self)`. Verify this in the SoCo source
   at `.venv/lib/python3.12/site-packages/soco/core.py`.
3. **Apparatus next, then the spec, then docs.**

## Edge Cases
- **The apparatus `topology`** reads each group's row from that row's
  coordinator's own view, at the moment it is read. It is not a single
  simultaneous snapshot. Document this in its help text.
- **Worst-case latency**: `_on_coordinator` adds at most about 3 s per call
  under a genuine, non-transient view failure. Acceptable against
  `play_stream`'s existing settle sleeps.
- **`say`'s `with_stale_coord_retry`** does one invalidate-and-resolve
  retry with no bounded wait. It passed on hardware, and is left as it is.
  Note the asymmetry in CLAUDE.md as a follow-up candidate.
- **`fast_path` with no mutations**: still end with `_sync_view(c0,
  expect_coordinator=True)`. It's cheap, and the cache may hold another
  speaker's view from `_plan_targets`' snapshot.
- **`detach=False` merges**: `c0` is the merge base's coordinator. Sync
  from `c0` last.
- **`say(["all"])`**: `_say_all` is unchanged and out of scope. Its
  follower-URI oddity in step 10 is noted, not a defect.

## Files Affected
- `mcp_sonos/controller.py`
- `tests/_fakes.py`
- new or updated test files
- `targeting_smoke.py`
- `tests/behavior/target-set-playback.md`
- `CLAUDE.md`

## Citation Audit (2026-09-29)
Each citation was checked against `c34d716`:
- `controller.py:_execute_plan`: stop → unjoin → join, then
  `_confirm_final_membership`, then `_confirm_bystanders_stopped`, then
  `TargetGroup(members=_group_members_of(c0))`
- `_confirm_bystanders_stopped`: `coord = _coordinator_of(s)` per bystander
- `play_stream`: `coord.stop()` / `coord.play_uri(...)`, and the final
  `RuntimeError(... "The stream may be incompatible with this speaker
  model.")`
- `targeting_smoke.py`: `cmd_stop_all` (`except Exception: pass`),
  `cmd_restore_state`, `cmd_topology`, `cmd_group`, `cmd_mute_all`,
  `cmd_save_state`

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
