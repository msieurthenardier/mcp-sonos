# Leg: verify-integration

**Status**: completed
**Flight**: [Reap-Resilient Control Surface](../flight.md)

> **HAT PASSED (2026-06-02).** Q4 reap+respawn: a fresh MCP process drove a live queue
> (`status` live state, `next` advanced Hausswolff→Saya Gray, `stop` halted, queue kept).
> Q6 say-resume: music → announcement → same track resumed **mid-track** (pos 0:05→0:07
> after the mid-track pivot; operator confirmed by ear). `play_url` shares the identical
> `_with_queue_resume` helper (unit-tested; a live play_url would block for the full clip,
> so taken as covered by say-live + units). 63 tests green.

## Objective
Confirm end-to-end on live hardware that the control surface works after an MCP
reap+respawn (Q4) and that `say`/`play_url` resume the queue (Q6).

## Context
- Legs 1–4 implemented + unit-tested (60 hardware-free tests green).
- This leg's automated half is already satisfied by that suite; the unique work is the
  manual HAT (FD-guided) on live speakers, plus an optional reap-control helper script.

## Acceptance Criteria
- [ ] Full hardware-free suite green (`pytest -q`) — 60 tests (already satisfied by legs 1–4)
- [ ] **Q4 reap+respawn HAT**: with a native queue playing and NO live MCP session, a
      FRESH MCP process drives the queue: `playlist_status` shows live state
      (artist/album, engine native_queue), `playlist_next` advances, `playlist_stop`
      stops (queue kept)
- [ ] **Q6 resume HAT**: with a queue playing, `say` (and `play_url`) plays the clip and
      the queue resumes mid-track, best-effort (operator confirms by ear; falls back to
      start-of-track if the host rejects the seek)
- [ ] Findings recorded in the flight log; gate any divergence

## Verification Steps (operator-run, FD-guided)
1. Load an external queue (helper script), leave it playing, process exits (the reap).
2. From a fresh MCP process, call `playlist_status` → confirm live state + engine.
3. `playlist_next` → confirm advance; `playlist_stop` → confirm stop, queue intact.
4. Reload a queue; `say(...)` → confirm announcement then queue resumes; repeat for `play_url`.
5. Operator confirms by ear / output; FD records.

## Files Affected
- Optional throwaway reap-control helper (outside the repo tree); no source changes.
