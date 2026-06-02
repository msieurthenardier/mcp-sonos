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
