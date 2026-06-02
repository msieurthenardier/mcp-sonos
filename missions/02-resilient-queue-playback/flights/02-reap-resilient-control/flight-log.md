# Flight Log: Reap-Resilient Control Surface

**Flight**: [Reap-Resilient Control Surface](flight.md)

## Summary
Planned and design-reviewed. Status `ready`. Execution not yet started.

---

## Leg Progress

### Leg 1: stateless-control-surface — landed (2026-06-01)

**Status**: landed

**Changes**:
- `mcp_sonos/playlists.py`: Updated `next_track`, `previous_track`, `stop`, and `status` to capture `coord` from `_resolve_coordinator` in all four methods. Added live-coordinator branch when `sess is None`: `next`/`previous` call `coord.next()`/`coord.previous()` in try/except and return live track info; `stop` calls `coord.stop()` without clearing the queue; `status` reads `get_current_transport_info()` + `get_current_track_info()` and returns full state or idle dict. All four return `engine: "native_queue"`. Worker-session path unchanged.
- `tests/_fakes.py`: Extended `SoCoFake._track` default dict with `artist`, `album`, `position`, `duration`, `playlist_position` keys. Added `next_call_count`, `previous_call_count`, `stop_call_count` fields (default 0). `next()`, `previous()`, `stop()` now increment their respective counters.
- `tests/test_queue_path.py`: Replaced three legacy no-session tests (asserting `controllable:false`/`running:false`) with seven new tests covering: `next`/`previous` invoke `coord.next()`/`coord.previous()` and return live track info; `stop` calls `coord.stop()` and does not clear the queue; `status` returns live state with `artist`/`album` when PLAYING; `status` returns idle dict when STOPPED; `next_track` swallows SoCo errors; worker-session path is unaffected by the new live-coordinator branch.

**Test result**: 45 passed in 0.88s (full suite green)

**Deviations**: None.

---

### Leg 2: retry-cache-flush-and-cleanup — landed (2026-06-01)

**Status**: landed

**Changes**:
- `mcp_sonos/playlists.py`: Added `invalidate_speakers_cache: Callable[[], None] = lambda: None` parameter to `PlaylistManager.__init__`; stored as `self._invalidate_speakers_cache`. Updated `_play_from_queue_with_stale_coord_retry`: changed signature to `-> None`, removed `return coord`/`return fresh_coord` statements, added `self._invalidate_speakers_cache()` call BEFORE `self._resolve_coordinator(name)` on `SoCoSlaveException`, rewrote the misleading comment to accurately explain why the explicit cache flush is necessary (re-resolving alone does not bypass the 30s TTL). Removed dead `_session_for` method (no callers confirmed via grep).
- `mcp_sonos/controller.py`: Passed `invalidate_speakers_cache=lambda: setattr(self, "_speakers_ts", 0.0)` when constructing `PlaylistManager`, mirroring the controller's `_play_uri_with_stale_coord_retry` which sets `self._speakers_ts = 0.0` directly.
- `tests/_fakes.py`: Added `call_log: list` field (records `"play_mode"` in the `play_mode` setter and `"play_from_queue"` in `play_from_queue`) and `play_from_queue_raise: Exception | None` field (raises on first call then clears for retry tests).
- `tests/test_queue_path.py`: Added two new tests — `test_play_mode_set_before_play_from_queue` (asserts `"play_mode"` precedes `"play_from_queue"` in `call_log`) and `test_slave_exception_retry_flushes_cache_and_succeeds` (injects `SoCoSlaveException` on first `play_from_queue`, asserts `invalidate_speakers_cache` spy called once, coordinator re-resolved, second call on fresh coord succeeds).

**Test result**: 47 passed in 0.87s (full suite green; 2 new tests added)

**Deviations**:
- `_session_for` confirmed to have zero callers (grep returned only the definition); removed without qualification.
- The test's resolve stub required `<= 2` stale returns (not `== 1`) because `play()` calls `_resolve_coordinator` once before `_play_via_queue` calls it a second time; both use the stale coord. This is correct behavior — the retry is the third call.

---

### Post-review fix: engine:"worker" consistency + test completeness (2026-06-01)

**Status**: complete (not a leg — review-item fix)

**Changes**:
- `mcp_sonos/playlists.py`: Added `"engine": "worker"` key to the worker-session return dicts of `next_track` (signaled:"next"), `previous_track` (signaled:"previous"), `stop` (stopped:True), and `status` (sess.to_dict() augmentation). The "engine" discriminator is now present on every control-tool response regardless of which engine is active. All existing keys preserved; strictly additive.
- `tests/test_queue_path.py`: Added engine:"worker" assertion to existing `test_worker_session_path_unchanged_for_next`. Added two parallel regression tests — `test_worker_session_path_unchanged_for_previous` (verifies `back_event` signaled, `coord.previous()` NOT called, `engine:"worker"` returned) and `test_worker_session_stop_returns_engine_worker` (verifies `stopped:True`, `engine:"worker"` returned from worker-session stop path).

**Test result**: 49 passed in 0.86s (full suite green; 2 new tests added)

---

## Manual HAT — Leg 3 takeover-spike (hard gate)

**Status**: PASS — gate decision PROCEED. (Throwaway spike, not committed; live Kitchen/Patio.)

Proved the snapshot→clip→restore mechanism for Leg 4:
- `coord.play_uri(clip)` over an active queue **preserved the queue** (`queue_size`
  stayed 2 throughout the clip and after stop).
- Resume works from a STOPPED coordinator whose source was changed to the clip URL:
  `play_from_queue(0)` returned to playlist_position 1 (Anna von Hausswolff), operator
  confirmed by ear it restarted from the top.
- **Off-by-one confirmed**: 1-based `playlist_position` (snapshot=1) → `play_from_queue(0)`
  lands on the same track. Leg 4 uses `index = playlist_position - 1`.
- `play_mode` read (`NORMAL`) and restored.
- Clip-end detection: simulated via explicit `stop()` (the novel part — resume FROM
  STOPPED — is proven). Natural clip-end → STOPPED is already handled by `say()`'s
  `_wait_until_stopped` poll in production; Leg 4 reuses it (extends to `play_url`).

---

### Leg 4: queue-aware-takeover — landed (2026-06-02)

**Status**: landed

**Changes**:
- `mcp_sonos/controller.py`:
  - Added `Callable` import.
  - Added `PLAY_URL_RESUME_TIMEOUT_SECONDS` constant (default 3600, env-overridable via `PLAY_URL_RESUME_TIMEOUT_SECONDS`).
  - Added `_with_queue_resume(coord, speaker_uid, run_clip, *, timeout)` helper: snapshots `(index, play_mode)` when a native queue is actively playing (`queue_size > 0` AND PLAYING AND `int(playlist_position) > 0` AND no worker session for `speaker_uid`), calls `run_clip()`, blocks via `_wait_until_stopped`, then resumes via `coord.play_from_queue(index)` + `coord.play_mode = saved` (best-effort, exceptions swallowed).
  - Rewired `say()` single-speaker path: replaced direct `_play_uri_with_stale_coord_retry` + `_wait_until_stopped` with a `_play_clip` closure and `_with_queue_resume`, passing `s.uid` (named speaker's UID) and `timeout=TTS_TIMEOUT_SECONDS`. `_say_all` path unchanged.
  - Rewired `play_url()`: replaced fire-and-forget `coord.play_uri` with `_with_queue_resume`; updated docstring to document the blocking contract change and best-effort resume. `play_file()` inherits via `play_url()`.
- `mcp_sonos/playlists.py`: Added `has_active_session(speaker_uid) -> bool` predicate; reads `_sessions` under lock; comment documents the check-then-act race is benign (single-threaded at tool-call level).
- `tests/_fakes.py`:
  - `play_uri` now MERGES into `_track` (preserves `playlist_position`, `artist`, `album`) instead of replacing it, so snapshot tests work.
  - Added `play_from_queue_last_index: int | None` field (records last index passed to `play_from_queue`).
  - Added `partymode()` no-op stub (needed by `_say_all` path in new tests).
- `tests/test_queue_resume.py`: New test file, 11 tests covering: `say` resumes at correct index + restores play_mode; non-default play_mode restored; `play_url` blocks with generous timeout + resumes; `play_url` returns post-resume state; `play_file` inherits resume; no-queue skip (3 guard conditions tested: empty queue, STOPPED transport, position "0"); worker-session active skip; `say("all")` no resume; resume failure swallowed.

**Test result**: 60 passed in 2.50s (full suite green; 11 new tests added)

**Takeover / grouping semantics documented**:
- Snapshot keys on the named speaker's UID (`s.uid`), matching `_sessions` keying; NOT the coordinator's UID.
- Resume targets the coordinator at snapshot time. If grouping changed while the clip played, the resume may land on a different device — best-effort, no group reconstruction.
- `say("all")` / `_say_all`: group is dissolved before the clip; no queue resume attempted (documented limitation; group reconstruction is out of scope).
- Worker-session active: worker owns its lifecycle; the snapshot guard `has_active_session` causes the resume to be skipped — the worker will resume on its own schedule.
- MCP reaped mid-clip for a long `play_url`: resume is lost; best-effort, swallowed.
- `play_url` contract change: was fire-and-forget; now blocks until clip-end (or PLAY_URL_RESUME_TIMEOUT_SECONDS). Live streams that never stop simply don't auto-resume after the cap.

**Deviations**:
- `say()` wraps the `_play_uri_with_stale_coord_retry` call inside a `_play_clip` closure (via `coord_holder`) so the helper can update the coordinator reference if the stale-coord retry fires. The snapshot and `_wait_until_stopped` still use the original coord from before the retry in that rare path — the stale-coord retry + queue resume corner case is best-effort and the existing stale-coord tests patch `_wait_until_stopped` to a no-op, so no regression.

---

### Leg 4 (reopened): mid-track seek addition — landed (2026-06-02)

**Status**: landed

**Changes**:
- `mcp_sonos/controller.py` — `_with_queue_resume`: snapshot now also captures
  `saved_position` from `track_info.get("position")` inside the existing guarded
  snapshot block. On resume, after `play_from_queue(saved_index)`, calls
  `coord.seek(saved_position)` wrapped in its OWN inner `try/except` (seek failures
  swallowed — start-of-track fallback). Seek is skipped when `saved_position` is `None`
  or `"0:00:00"` (trivial offset). Order: `play_from_queue` → `seek` (own try/except) →
  `play_mode` restore. The outer best-effort try/except around the whole resume block is
  unchanged.
- `tests/_fakes.py` — `SoCoFake`: added `seek_raise: Exception | None` and
  `seek_last: str | None` fields; added `seek(timestamp)` method that records
  `seek_last = timestamp` then raises `seek_raise` if set.
- `tests/test_queue_resume.py`: updated all five existing queue-resume tests that exercise
  the happy path to also assert `speaker.seek_last == "0:01:30"` (the default position in
  `_make_speaker_playing_queue`). Added three new tests:
  - `test_seek_called_with_snapshot_position`: explicit override to `"0:02:45"`, asserts
    seek is called with that exact value.
  - `test_seek_failure_swallowed_resume_still_completes`: injects `seek_raise`; asserts no
    exception propagates, `play_from_queue_last_index == 0`, `seek_last` recorded, and
    `play_mode` still restored.
  - `test_seek_skipped_when_position_is_zero`: sets position to `"0:00:00"`; asserts
    `seek_last is None` (seek not attempted).

**Test result**: 63 passed in 2.57s (full suite green; 3 new tests added, 14 total in test_queue_resume.py)

**Deviations**: None.

---

## Decisions

_None yet._

---

## Deviations

_None yet._

---

## Anomalies

_None yet._

---

## Session Notes

### Design review (Architect)
Verdict: **approve with changes**. Findings folded into the spec before `ready`:
- [high] Leg 3 spike must verify the restore sequence explicitly: `play_from_queue(index)`
  works on a STOPPED coordinator after `play_uri` changed the source; `playlist_position`
  is 1-based → `play_from_queue` 0-based (off-by-one). (Seek dropped — resume is start-of-track.)
- [high] Clip-end detection: `say()` already blocks via `_wait_until_stopped`; `play_url()`
  is fire-and-forget. Decision (operator): `play_url` will block the same way then resume —
  its return-immediately contract changes (documented); long-`play_url` resume is best-effort
  under reap.
- [med] `say("all")` unjoins/destroys the group and is out of auto-resume scope —
  documented limitation in Leg 4; no group reconstruction.
- [med] `stop` keeps the queue (coord.stop(), no clear) — spike confirms resume-after-stop.
- [low] `invalidate_speakers_cache: Callable[[],None]`; `_track_state` not exported →
  read transport/track info directly in playlists.py; `SoCoFake` needs `artist`/`album`
  + `next`/`previous` call-recording.
Operator decisions: auto-resume covers BOTH `say` and `play_url`; resume point is
**start-of-track** (no seek → external-MP3 seekability risk removed). Second review
cycle skipped — changes were direct incorporations of the Architect's recs + those decisions.

### Flight Director Notes — pivot: mid-track resume (post-Leg-5)
During the Leg 5 HAT the operator revised the resume-point decision: start-of-track is
wrong UX; the queue should pick up **where it was interrupted**. A Leg 5 seek spike
proved the external host (gramotunes) honors HTTP range requests — `seek('0:00:21')`
after `play_from_queue(0)` landed at `0:00:23`, PLAYING (operator confirmed by ear).
Rationale + decision: reopen Leg 4 to snapshot `position` and resume via
`play_from_queue(index)` → `seek(position)`, wrapped in try/except so hosts WITHOUT
range support fall back to start-of-track (best-effort). The earlier "start-of-track"
framing in the Design Review notes above is superseded by this entry. Treating
mid-track best-effort as the live spec going forward.

### Leg 5: verify-integration — completed (2026-06-02)
**Status**: completed. Suite: 63 tests green.
- **Q4 reap+respawn HAT** (reap_test.py loads queue + exits; reap_control.py fresh process):
  `playlist_status` returned live state (engine native_queue, artist/album, playlist_position);
  `playlist_next` advanced Hausswolff→Saya Gray (pos 1→2); `playlist_stop` halted, queue kept.
  Operator confirmed the audible skip + stop.
- **Q6 say-resume HAT** (say_resume.py): music → spoken announcement → same track resumed
  mid-track (position 0:05 before → 0:07 after the mid-track pivot). Operator confirmed by ear.
- **Mid-track pivot** (Leg 4 reopened): `_with_queue_resume` now snapshots `position` and
  `seek()`s after `play_from_queue`, wrapped in its own try/except (start-of-track fallback for
  hosts without HTTP range support). +3 tests (seek attempted / seek-failure swallowed / zero-pos skip).
- `play_url` resume not run live (shares the identical helper; a live clip blocks the full
  duration) — covered by say-live + unit tests.
