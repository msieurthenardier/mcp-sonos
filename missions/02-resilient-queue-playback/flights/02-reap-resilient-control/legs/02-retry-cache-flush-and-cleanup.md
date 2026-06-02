# Leg: retry-cache-flush-and-cleanup

**Status**: completed
**Flight**: [Reap-Resilient Control Surface](../flight.md)

## Objective
Make the queue-path stale-coordinator retry actually flush the speaker cache (it
currently only re-resolves through the 30s-TTL cache), remove dead code, and add the
two missing tests from the Flight 1 debrief.

## Context
- Flight 1 debrief: `_play_from_queue_with_stale_coord_retry` (`playlists.py:633`) has a
  comment claiming it "invalidates the speakers cache by re-resolving" — but
  `_resolve_coordinator` → `_speakers_fresh()` uses a 30s TTL, so a retry within 30s
  reuses the stale coordinator. The controller's `_play_uri_with_stale_coord_retry`
  correctly sets `self._speakers_ts = 0.0` first. This leg gives the queue retry parity.
- Dead code: `_session_for` (`playlists.py:670`) is no longer called (the control
  methods read `_sessions` directly since Leg 1); the retry helper's return value is
  unused by its caller (`_play_via_queue` discards it).
- Missing tests (debrief): `play_mode`-set-before-`play_from_queue` ordering; the
  `SoCoSlaveException` retry branch (now also asserting the cache flush).
  (`status()` no-session was already covered in Flight 2 Leg 1.)

## Inputs
- `mcp_sonos/playlists.py` — `PlaylistManager.__init__`, `_play_from_queue_with_stale_coord_retry`,
  `_play_via_queue`, `_session_for`.
- `mcp_sonos/controller.py` — where `PlaylistManager(...)` is constructed; `_speakers_ts`.
- `tests/_fakes.py`, `tests/test_queue_path.py`.

## Outputs
- `invalidate_speakers_cache` injected and called on retry.
- Dead code removed; unused return dropped.
- Two new tests; full suite green.

## Acceptance Criteria
- [x] `PlaylistManager.__init__` accepts `invalidate_speakers_cache: Callable[[], None]`
      (optional, default no-op so existing direct constructions/tests don't break),
      stored as an attribute
- [x] `controller.py` constructs `PlaylistManager` with `invalidate_speakers_cache` wired
      to flush its speaker cache (mirrors the controller's `_speakers_ts = 0.0` reset)
- [x] `_play_from_queue_with_stale_coord_retry` calls `self._invalidate_speakers_cache()`
      BEFORE re-resolving on `SoCoSlaveException`; its now-misleading comment is corrected;
      its return value is dropped (`-> None`) and the caller updated accordingly
- [x] `_session_for` is removed (confirm no remaining callers first)
- [x] New test: `_play_via_queue` sets `play_mode` BEFORE calling `play_from_queue`
      (ordering invariant — swapping them would be a real bug)
- [x] New test: when `play_from_queue` raises `SoCoSlaveException` once, the retry calls
      `invalidate_speakers_cache`, re-resolves, and the second call succeeds
- [x] Full suite green

## Verification Steps
- `pytest -x -q` (with timeout) passes including the two new tests.
- The cache-flush test asserts the injected callback was invoked during retry.

## Implementation Guidance
1. Add the `invalidate_speakers_cache` param (default `lambda: None`) to
   `PlaylistManager.__init__`; store as `self._invalidate_speakers_cache`.
2. In `controller.py`, pass a callable that resets the controller's speaker-cache
   timestamp (e.g. `invalidate_speakers_cache=self._invalidate_speakers_cache` or a
   small lambda setting `self._speakers_ts = 0.0`).
3. In the retry helper: on `SoCoSlaveException`, call `self._invalidate_speakers_cache()`
   then `self._resolve_coordinator(name)`; fix the comment; change signature to `-> None`
   and remove `return` statements; update `_play_via_queue` (it already discards the value).
4. Delete `_session_for` after grepping for callers.
5. For the ordering test, record call order on `SoCoFake` (e.g. append to a list in
   `play_mode` setter and `play_from_queue`) and assert `play_mode` precedes `play_from_queue`.

## Edge Cases
- **Default no-op callback**: direct `PlaylistManager(...)` constructions without the new
  param must still work (existing tests) — hence the default.

## Files Affected
- `mcp_sonos/playlists.py`, `mcp_sonos/controller.py`, `tests/_fakes.py`, `tests/test_queue_path.py`
