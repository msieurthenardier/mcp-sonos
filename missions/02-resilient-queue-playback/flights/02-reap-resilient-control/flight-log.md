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
