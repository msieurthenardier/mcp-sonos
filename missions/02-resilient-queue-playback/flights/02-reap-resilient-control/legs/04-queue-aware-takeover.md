# Leg: queue-aware-takeover

**Status**: landed
**Flight**: [Reap-Resilient Control Surface](../flight.md)

> **Reopened post-Leg-5 (mid-track pivot).** Operator revised resume to pick up where
> interrupted, not from the top. Leg 5 seek spike confirmed the host honors HTTP range
> requests. Snapshot now adds `position`; resume does `play_from_queue(index)` →
> `seek(position)` wrapped in try/except (falls back to start-of-track if the host
> rejects the seek). See flight-log FD Notes.

## Objective
Make `say` and single-coordinator `play_url` snapshot an active native queue, play the
clip, then resume the queue at start-of-track — so an announcement no longer silently
ends queue playback. (Q6)

## Context
- Leg 3 (hardware gate) proved the recipe: `play_uri` preserves the queue; resume via
  `play_from_queue(playlist_position - 1)` from STOPPED; `play_mode` snapshot/restore;
  start-of-track (no seek). Read the Leg 3 flight-log entry.
- `say()` already blocks via `_wait_until_stopped` (controller.py); `play_url()` is
  fire-and-forget and will be changed to block the same way then resume (its
  return-immediately contract changes — documented).
- Auto-resume runs ONLY on the native-queue path (no worker session) and only for a
  single coordinator. `say("all", ...)` (`_say_all`) destroys the group → out of scope
  (documented limitation, no group reconstruction).

## Inputs
- `mcp_sonos/controller.py` — `say`, `_say_all`, `play_url`, `_wait_until_stopped`,
  `_resolve_coordinator`; `self.playlists` (to detect an active worker session).
- `mcp_sonos/playlists.py` — a way to ask "is a worker session active for this speaker?"
  (add a small public predicate if none exists).
- `tests/_fakes.py`, `tests/`.

## Outputs
- A shared snapshot→clip→resume helper used by `say` (single) and `play_url`.
- `play_url` now blocks until clip-end then resumes (contract change, documented).
- Hardware-free tests; takeover + grouping semantics documented at decision level.

## Design Decisions (from design review)
- **Snapshot keys on the named speaker's UID.** `_sessions` is keyed by `s.uid` (the
  named speaker from `_resolve_coordinator(name)[0]`), NOT the coordinator's — pass
  `s.uid` to `has_active_session`. Guard the queue check with `int(playlist_position) > 0`
  in try/except (the field is a string; `"0"` is meaningless).
- **`play_url` timeout = generous safety cap, separate from TTS's 30s.** `play_url`
  blocks until clip-end (the chosen contract) but with a generous cap (new configurable
  constant, e.g. `PLAY_URL_RESUME_TIMEOUT_SECONDS`, default ~3600) so a never-stopping
  live stream doesn't hang the MCP forever; clips/streams exceeding the cap simply don't
  auto-resume (best-effort, documented). `say` keeps `TTS_TIMEOUT_SECONDS = 30`.
- **`play_file` inherits resume via `play_url`** — no separate wiring; covered by one test
  or an explicit exclusion note.
- **`play_url` returns post-resume state** — `_track_state(coord)` after the resume (reflects
  the resumed queue track, not the clip).
- **Helper takes `speaker_uid` as a parameter** (caller already has `s.uid`).

## Acceptance Criteria
- [x] A shared helper (taking `speaker_uid`) snapshots `(queue_index = playlist_position - 1,
      play_mode)` when a native queue is actively playing on the coordinator
      (`queue_size > 0` AND PLAYING AND `int(playlist_position) > 0`), runs the clip, blocks
      via `_wait_until_stopped`, then `coord.play_from_queue(queue_index)` + restores `play_mode`
- [x] **(mid-track pivot)** Snapshot ALSO captures `position` (from
      `get_current_track_info()["position"]`); on resume, after `play_from_queue(index)`,
      call `coord.seek(position)` wrapped in its OWN try/except so a host that rejects the
      seek (no HTTP range support) falls back to start-of-track without raising. A test
      asserts seek is attempted with the snapshot position, and a separate test asserts a
      seek failure is swallowed (resume still succeeds at start-of-track).
- [x] `say` (single speaker) auto-resumes the queue after the announcement
- [x] `play_url` (single coordinator) auto-resumes too; it now BLOCKS until clip-end with a
      generous cap (documented contract change); returns post-resume `_track_state(coord)`
- [x] `play_file` inherits the resume via `play_url` (one test or an explicit exclusion note)
- [x] Auto-resume is SKIPPED when: nothing is playing / no queue; OR a **worker session**
      is active for `s.uid` (worker owns its lifecycle); OR the call is `say("all", ...)` /
      `_say_all` (group destroyed — documented limitation)
- [x] If snapshot/restore fails (e.g. MCP-reaped mid-clip for a long `play_url`), the clip
      still plays and the failure is swallowed (best-effort resume) — no raise
- [x] `has_active_session(speaker_uid)` added to `PlaylistManager` (with a comment that the
      check-then-act race is benign — single-threaded at the tool-call level)
- [x] Takeover contract + `say("all")` limitation + grouping documented at decision level
- [x] Hardware-free tests cover: say resumes; play_url resumes + blocks; play_file inherits;
      no-queue skip; worker-session skip; `say("all")` skip; resume-failure swallowed.
      `SoCoFake.play_uri` MERGES `_track` (preserves `playlist_position`/`artist`/`album`)
      rather than replacing it, so snapshot tests work. Full suite green.

## Verification Steps
- `pytest -x -q` (with timeout) green including new tests.
- Live confirmation of say/play_url resume is part of Leg 5 (reap+respawn HAT).

## Implementation Guidance
1. Add a predicate to `PlaylistManager` (e.g. `has_active_session(speaker_uid) -> bool`)
   so the controller can tell native-queue playback from a worker session.
2. Add a controller helper, e.g.
   `_with_queue_resume(coord, speaker_uid, run_clip: Callable[[], None], *, timeout)`:
   - Snapshot: if `not self.playlists.has_active_session(speaker_uid)` AND
     `coord.queue_size > 0` AND transport PLAYING AND `int(playlist_position) > 0`
     → capture `(index = playlist_position - 1, play_mode)`; else "no resume".
   - `run_clip()` (the `play_uri` call).
   - `_wait_until_stopped(coord, timeout=timeout)`.
   - If snapshotted: `coord.play_from_queue(index)`; `coord.play_mode = saved` — all in
     try/except (best-effort; swallow on failure).
   - `say` passes `TTS_TIMEOUT_SECONDS`; `play_url` passes the new generous cap.
3. `say` (single path) and `play_url` wrap their `play_uri` in `_with_queue_resume`.
   `play_url` thus blocks now — update its docstring/return accordingly.
4. `_say_all` does NOT use the helper (documented limitation).
5. Tests via `SoCoFake` — may patch `_wait_until_stopped` to return promptly.

## Edge Cases
- **MCP reaped mid-clip** (long `play_url`): resume lost — best-effort, swallowed, documented.
- **Worker session active**: skip (worker takeover detection handles it).
- **say("all")**: group destroyed; no resume; documented.
- **Nothing playing**: no snapshot, no resume.

## Files Affected
- `mcp_sonos/controller.py` — `say`/`play_url`/new helper
- `mcp_sonos/playlists.py` — `has_active_session` predicate
- `tests/_fakes.py`, `tests/` — new takeover-resume tests
