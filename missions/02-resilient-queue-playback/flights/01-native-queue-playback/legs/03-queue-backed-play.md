# Leg: queue-backed-play

**Status**: completed
**Flight**: [Native Queue Playback Path](../flight.md)

## Objective
Re-back `playlist_play` on Sonos's native queue for all-external playlists so
playback advances speaker-side and survives an MCP reap, while any playlist
containing an MCP-hosted URL transparently falls back to the unchanged worker engine.

## Context
- Leg 1 (hardware) proved the recipe and is the source of truth — read its
  flight-log entry. Key facts: bare URLs are rejected; DIDL objects required;
  native multi-track advancement works; no stale-coord symptom seen; titles are
  inconsistent (filename floor). Sonos app display is de-scoped.
- Leg 2 added `is_mcp_hosted(url, host_ip, port)` in `mcp_sonos/_urls.py`.
- Flight DDs: routing by classification; native `play_mode`; per-coordinator
  queue ops; evict worker before queue play; wrap `play_from_queue` in
  stale-coord retry (insurance).
- **Scope boundary:** this leg delivers queue-backed *play* only. The control
  surface (`playlist_next`/`previous`/`stop`/`status`) against a queue-backed
  playlist is **Flight 2**. This leg must ensure those worker-based tools
  **fail gracefully (no crash)** when called on a speaker that's playing from the
  queue with no `_sessions` entry — it need not make them functional.

## Inputs
- `mcp_sonos/playlists.py` (`PlaylistManager`, `_sessions` keyed by speaker UID,
  worker `play()`/`_worker()`, manual shuffle ~line 227).
- `mcp_sonos/controller.py` (`_coordinator_of`/`_resolve_coordinator`,
  `_play_uri_with_stale_coord_retry`, `audio` → `AudioHost` with `host_ip`/`port`).
- `mcp_sonos/_urls.py` `is_mcp_hosted` (Leg 2).
- `tests/_fakes.py` `SoCoFake` (currently no-op `add_to_queue`/`clear_queue`).

## Outputs
- `playlist_play` routes all-external playlists to a new queue-backed code path;
  mixed/MCP-hosted playlists to the existing worker engine (unchanged).
- A queue-load helper that builds DIDL items and enqueues on the coordinator.
- `SoCoFake` extended with real queue state for tests.
- Hardware-free tests for routing, fallback, worker-eviction, and `play_mode`.

## Design Decisions (resolved from design review)
- **DD-A — sibling retry helper.** `_play_uri_with_stale_coord_retry` is hardcoded
  to `coord.play_uri`; do NOT refactor it (it's pinned by `say()` tests). Add a
  sibling `_play_from_queue_with_stale_coord_retry(name, coord, index)` that mirrors
  the recover-once pattern but calls `coord.play_from_queue(index)`.
- **DD-B — `SHUFFLE_NOREPEAT`, not `SHUFFLE`.** SoCo's `SHUFFLE` implies repeat=True
  (loops forever); use `SHUFFLE_NOREPEAT` to match the worker engine's one-pass
  behavior. Leave a code note.
- **DD-C — return shape.** Queue path returns the same shape as the worker `play()`
  plus `"engine": "native_queue"` (worker path implicitly/explicitly `"worker"`),
  so Flight 2's control tools can tell which engine is active.
- **DD-D — eviction follows `stop()` not `play()`.** Evict with `_signal_stop(prev)`
  **and** `coord.stop()` (the `stop()` pattern), then **join to completion (≤2 s)
  BEFORE** any `clear_queue`. Signal+stop+join are one unit — do not interleave the
  DIDL build or queue ops between them.
- **DD-E — DIDL ids.** `item_id=f"track-{i}"`, `parent_id` = a module-level constant
  that is NOT `"-1"` (the Leg 1 spike verified a non-`"-1"` value carries titles;
  `"-1"` loses them). Leg 4 (HAT) confirms titles stick on hardware.

## Acceptance Criteria
- [x] An all-external playlist started via `playlist_play` enqueues all tracks via
      `coord.add_multiple_to_queue([...DidlMusicTrack...])` and starts
      `coord.play_from_queue(start_index)` (0-based, maps 1:1 to queue position) —
      verified against `SoCoFake` (Q1/Q2 mechanism)
- [x] DIDL items use `parent_id != "-1"` (DD-E), `item_id=f"track-{i}"`, a
      `DidlResource` with `protocol_info="http-get:*:audio/mpeg:*"`, a URL-encoded
      URI, and the playlist item's title (filename-derived fallback when empty) (Q2)
- [x] Shuffle → native `play_mode = SHUFFLE_NOREPEAT`; normal → `NORMAL` (DD-B),
      NOT the in-process permutation at `playlists.py:227`, on the queue path (Q3)
- [x] A playlist containing ANY MCP-hosted URL (via `any_mcp_hosted(urls,
      controller.audio.host_ip, controller.audio.port)`) routes to the existing
      worker engine; that path's behavior is unchanged (Q5)
- [x] On a queue-path play, any existing worker `_sessions[speaker.uid]` is
      signalled + `coord.stop()`ed + joined to completion BEFORE the queue is
      cleared/loaded (DD-D, no race) (Q6-partial)
- [x] `play_from_queue` runs through the new `_play_from_queue_with_stale_coord_retry`
      sibling helper (DD-A); all queue ops run on the resolved coordinator
- [x] `playlist_next` and `playlist_previous` no longer raise on a no-session
      speaker — they return a graceful dict (e.g. `{"controllable": false,
      "engine": "native_queue"}`); `playlist_stop`/`playlist_status` already no-op
      gracefully and need no change (full queue control is Flight 2)
- [x] `SoCoFake` extended with list-backed `_queue`: `add_multiple_to_queue`
      (appends, returns None), `play_from_queue`, `clear_queue`, `play_mode`
      (get/set), `queue_size` (`@property` → `len(self._queue)`), and
      `is_coordinator = True` (since `play_from_queue`/`clear_queue` are
      `@only_on_master` in real SoCo)
- [x] New hardware-free tests cover: all-external → queue calls (assert item count
      + titles + `play_from_queue`); mixed → worker fallback; worker-active →
      queue-play eviction handoff; shuffle → `play_mode == SHUFFLE_NOREPEAT`.
      Full suite green.

## Verification Steps
- `pytest -x -q` (with a timeout) passes including new tests.
- Tests assert the `SoCoFake` received `add_multiple_to_queue` with the expected
  item count/titles and `play_from_queue`, and that the worker path is taken for
  mixed playlists.
- Live-hardware confirmation of titles/advancement is **Leg 4** (manual HAT), not
  this leg.

## Implementation Guidance
1. **Add `any_mcp_hosted(urls, host_ip, port)` to `_urls.py`** (one-liner over
   `is_mcp_hosted`). Classify in `playlist_play`: all-external → queue path; any
   MCP-hosted → existing worker engine.
2. **Queue path** (new helper, e.g. `PlaylistManager._play_via_queue` or a
   controller method — implementer's call, but keep grouping invariants):
   a. **Evict** existing worker session for `speaker.uid` as ONE unit (DD-D):
      `_signal_stop(prev)` + `coord.stop()`, then `prev.thread.join(timeout=2.0)`
      to completion. Do NOT run any queue op (step d) until the join returns.
   b. Resolve the coordinator via `_resolve_coordinator`/`_coordinator_of`.
   c. Build DIDL items per the Leg 1 recipe + DD-E (`title` from item, filename
      fallback; `parent_id` non-`"-1"` constant; `item_id=f"track-{i}"`; URL-encode
      the URI; `DidlResource(..., "http-get:*:audio/mpeg:*")`).
   d. `coord.clear_queue()`, `coord.add_multiple_to_queue(items)`.
   e. Set `coord.play_mode = "SHUFFLE_NOREPEAT" if shuffle else "NORMAL"` (DD-B).
      Add a code note: `# SHUFFLE_NOREPEAT intentional — one pass, like worker path`.
   f. Start via `self._play_from_queue_with_stale_coord_retry(name, coord, start_index)`
      (DD-A) — a new sibling of `_play_uri_with_stale_coord_retry` calling
      `coord.play_from_queue(index)`.
   g. Return the worker `play()` shape + `"engine": "native_queue"` (DD-C).
3. **Graceful no-session control (DD / low issue)**: make `playlist_next` and
   `playlist_previous` return a graceful dict instead of raising when
   `_sessions` has no entry. Leave `playlist_stop`/`playlist_status` as-is.
4. **Do not remove or alter the worker engine** — it remains the fallback (Q5).
5. **Extend `SoCoFake`** (list-backed `_queue`, `is_coordinator=True`, `play_mode`
   get/set, `queue_size` property) so steps d–f are assertable.
6. **Tests** in the existing pytest layout reusing `SoCoFake`.

## Edge Cases
- **Empty playlist**: keep current `playlist_play` behavior (error/no-op as today).
- **start_index out of range**: clamp/validate as the worker path does.
- **Shuffle + start_index**: native `play_mode` handles ordering; `start_index`
  selects the queue position to begin — do not also permute in-process.
- **Queue-path playback then `playlist_stop`**: no session → must not raise
  (Flight 2 makes it actually stop the queue).
- **Group changes mid-playback**: native queue advances on the coordinator; we do
  not poll. Acceptable (documented).

## Files Affected
- `mcp_sonos/playlists.py` and/or `mcp_sonos/controller.py` — routing, queue path,
  `_play_from_queue_with_stale_coord_retry` sibling helper (DD-A), graceful
  `playlist_next`/`previous` no-session handling
- `mcp_sonos/_urls.py` — `any_mcp_hosted(urls, host_ip, port)` composition helper
- `tests/_fakes.py` — extend `SoCoFake` (list-backed queue, `is_coordinator`, etc.)
- `tests/` — new queue-path tests
