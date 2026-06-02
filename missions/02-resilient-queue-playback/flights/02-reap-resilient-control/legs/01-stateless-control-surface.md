# Leg: stateless-control-surface

**Status**: completed
**Flight**: [Reap-Resilient Control Surface](../flight.md)

## Objective
Make `status`/`next`/`previous`/`stop` operate on the live coordinator when there is
no `_sessions` entry (post-reap or native-queue playback), instead of reporting
`running:false`/`controllable:false`.

## Context
- Flight DD "Stateless control reads live coordinator state": with no session, drive
  the resolved coordinator directly. Worker-session path is unchanged.
- Flight 1 left these returning `{running:false}` / `{controllable:false}` for the
  native-queue path (the interim gap, now a mission Known Issue).
- `status` must report `artist`/`album` (the now-playing `title` is unreliable for
  queued items — Flight 1 ID3 finding). `_track_state` lives in `controller.py` and is
  NOT exported; read `coord.get_current_transport_info()` + `get_current_track_info()`
  directly in `playlists.py`.
- `stop` keeps the queue (DD): `coord.stop()` only, no `clear_queue`.

## Inputs
- `mcp_sonos/playlists.py` — `status`/`stop`/`next_track`/`previous_track` (~391-447),
  `_resolve_coordinator`, `_sessions`.
- `tests/_fakes.py` — `SoCoFake` (needs `artist`/`album` + `next`/`previous` recording).

## Outputs
- No-session control methods drive live coordinator state; `engine` key on all four.
- `SoCoFake` extended for the new assertions.
- Hardware-free tests.

## Acceptance Criteria
- [x] `next_track` with no session calls `coord.next()` and returns live track info
      (`engine: "native_queue"`), instead of `{controllable:false}`
- [x] `previous_track` with no session calls `coord.previous()` similarly
- [x] `stop` with no session calls `coord.stop()` (queue left intact — NO `clear_queue`)
      and returns `{stopped: true, engine: "native_queue", speaker: …}`
- [x] `status` with no session returns the live transport/track state read from the
      coordinator — `state`, `artist`, `album`, `position`, `duration`, `uri`,
      `playlist_position` — with `engine: "native_queue"`; idle result when STOPPED/empty
      is `{running: false, engine: "native_queue", speaker: <name>}` (engine key everywhere)
- [x] The three legacy no-session tests in `tests/test_queue_path.py` that assert the OLD
      behavior (`controllable:false` for next/previous, `running:false` for stop — ~lines
      334-365) are REPLACED with tests for the new live-coordinator behavior (these are
      intended behavior changes, not regressions; update stale docstrings too)
- [x] All four return the `engine` discriminator; the **worker-session path is unchanged**
      (when a session exists, behavior is exactly as before)
- [x] `next`/`previous`/`stop`/`status` do not raise on a coordinator with nothing
      queued/playing (SoCo errors swallowed → sensible dict)
- [x] `SoCoFake` extended: `get_current_track_info()` includes `artist`/`album`;
      `next()`/`previous()` record the call so tests assert the UPnP command was issued
- [x] New hardware-free tests cover each no-session path AND confirm the worker-session
      path is unaffected; full suite green

## Verification Steps
- `pytest -x -q` (with a timeout) passes including new tests.
- Tests assert `SoCoFake.next()`/`previous()`/`stop()` were invoked on the no-session
  path, and that `status` surfaces `artist`/`album` from the fake's track info.

## Implementation Guidance
1. Change `speaker, _ = self._resolve_coordinator(...)` to `speaker, coord = ...` in all
   four methods (only `stop` captures `coord` today). Keep the existing
   `sess = _sessions.get(speaker.uid)` lookup. `sess` exists → unchanged. `sess is None`
   → the new live-coordinator branch.
2. `status` no-session: read `coord.get_current_transport_info()["current_transport_state"]`
   and `coord.get_current_track_info()`; map to `state/title/artist/album/position/duration/
   uri/playlist_position` + `engine: "native_queue"`; STOPPED/empty → idle result above.
3. `next`/`previous` no-session: `coord.next()` / `coord.previous()` in try/except; then
   return live `get_current_track_info()` + `engine`. (Note: reading immediately after
   `next()` may briefly reflect the prior track on real hardware — acceptable; documented.)
4. `stop` no-session: `coord.stop()` in try/except; do NOT clear the queue.
5. `SoCoFake` already HAS `next()`/`previous()`/`stop()` (no-ops) — add call-recording
   (flag/counter) and extend the `_track` dict with `artist`/`album`/`position`/`duration`/
   `playlist_position` so `status` assertions work. Then add/replace tests (see AC).

## Edge Cases
- **Nothing playing / empty queue**: idle result, no raise.
- **`next` at end of queue**: SoCo may raise; swallow → sensible dict.
- **Worker session active**: unchanged path — do not regress takeover/skip/back.

## Files Affected
- `mcp_sonos/playlists.py` — four control methods
- `tests/_fakes.py` — `SoCoFake` extensions
- `tests/` — new stateless-control tests
