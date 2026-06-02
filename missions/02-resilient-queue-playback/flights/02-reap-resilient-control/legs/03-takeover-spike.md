# Leg: takeover-spike

**Status**: completed
**Flight**: [Reap-Resilient Control Surface](../flight.md)

## Objective
Empirically prove, on live hardware, the snapshot→clip→restore mechanism that Leg 4
will implement for `say`/`play_url` auto-resume — before any code is written.

## Context
- Hard gate (flight DD "Q6 = auto-resume"): no Leg 4 until this lands.
- Resume is **start-of-track** (operator decision), so NO seek — snapshot is just
  `(queue index, play_mode)` and restore is `play_from_queue(index)` + restore `play_mode`.
- This is a throwaway SoCo/HAT spike (not committed), against the live Kitchen/Patio group.

## Acceptance Criteria (gate questions)
- [ ] After `coord.play_uri(clip_url)` over an active queue, the loaded queue is
      **preserved** (`queue_size` unchanged)
- [ ] The clip's end is detectable (transport returns to STOPPED) — confirm a poll /
      `_wait_until_stopped`-style wait works
- [ ] `play_from_queue(index)` **resumes the queue** from a STOPPED coordinator whose
      transport source was changed to the clip URL by `play_uri`
- [ ] The 1-based `get_current_track_info()["playlist_position"]` → 0-based
      `play_from_queue(index)` off-by-one is confirmed (resume lands on the SAME track)
- [ ] `play_mode` can be read before and restored after (snapshot/restore)
- [ ] Decision recorded: clip-end detection approach for Leg 4; grouping note; gate = PROCEED/DIVERT
- [ ] If `play_uri` does NOT preserve the queue, or `play_from_queue` can't resume →
      DIVERT to "interrupt-only, documented" (flight Adaptation Criteria)

## Verification Steps (operator-run, FD-guided)
1. Load a 2+ track external queue on the Kitchen/Patio group.
2. Snapshot `playlist_position` (1-based) + `play_mode`.
3. `play_uri(clip)` — confirm queue_size unchanged; clip plays.
4. Wait for clip-end (poll transport → STOPPED).
5. `play_from_queue(snapshot_index - 1)` — confirm it resumes the same track from 0:00.
6. Restore `play_mode`; operator confirms by ear/inspection.

## Files Affected
- None in the repo (throwaway spike outside the tree).
