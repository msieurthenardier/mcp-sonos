# Flight: Reap-Resilient Control Surface

**Status**: in-flight
**Mission**: [Resilient Queue-Backed Playback](../../mission.md)

## Contributing to Criteria
- [ ] Q4 — After an MCP reap+respawn, `playlist_status`/`next`/`previous`/`stop`
  operate correctly against live speaker state with no reliance on the lost
  in-RAM `_sessions` entry
- [ ] Q6 — `say`/`play_url` interaction with an active queue is defined and
  documented (interrupt vs resume vs end), and grouping behavior of the queue
  path is documented
- [x] Flight 1 debrief carry-forwards (hygiene): stale-coord cache-flush on the
  queue retry; remove dead code (`_session_for`, unused retry return); add the
  missing tests (`play_mode` ordering, `status()` no-session, `SoCoSlaveException`)

---

## Pre-Flight

### Objective
Make the `playlist_*` control tools work against **live speaker state** after an
MCP reap (no `_sessions` dependency), and make `say`/`play_url` snapshot-and-resume
an active queue so an announcement no longer silently ends queue playback. Also
clears the Flight 1 debrief hygiene backlog in the same `playlists.py` surface.

### Open Questions
- [ ] Auto-resume mechanism (Q6) — narrowed by decisions below to: does
  `coord.play_uri(...)` preserve the loaded queue, and does `play_from_queue(index)`
  work on a STOPPED coordinator whose transport source was changed to a clip URL by
  `play_uri`? (Resume is **start-of-track**, so NO seek is needed.) Confirm the
  `get_current_track_info()["playlist_position"]` 1-based → 0-based off-by-one. →
  resolved by Leg 3 (hard gate, HAT).
- [x] Resume point → **start-of-track** (restart the interrupted queue track from
  0:00). Snapshot is just `queue index + play_mode + play state`; no `seek`, so the
  "are external MP3s seekable" risk is removed.
- [x] Auto-resume scope → **both `say` and `play_url`**. `say` already blocks via
  `_wait_until_stopped`; `play_url` will be changed to block the same way then
  resume (its previous return-immediately contract changes — documented). Reap
  durability: `say` re-wakes the MCP (reliable); a long `play_url` ties up the MCP
  for the clip and is best-effort (resume lost if the MCP is reaped mid-clip).
- [ ] Post-reap identity: with no session, control tools act on whatever the
  coordinator is currently playing — they cannot prove it's "our" queue. Confirm
  this is acceptable (documented limitation).

### Design Decisions

**Stateless control reads live coordinator state**: When `_sessions` has no entry,
`status`/`next`/`previous`/`stop` operate on the resolved coordinator's live state
(`get_current_transport_info`, `get_current_track_info`, `coord.next()/previous()/stop()`)
rather than returning `running:false`/`controllable:false`. The worker-session path
is unchanged.
- Rationale: Q4 — survive reap+respawn with no in-RAM state.
- Trade-off: can't distinguish "our" playback from unrelated (post-reap identity).

**`status` reports `artist`/`album`, not `title`**: Flight 1 found the now-playing
`title` is blank for queued items (ID3 precedence). Use `artist`/`album` for the
live status of queued tracks.

**`stop` keeps the queue**: no-session `stop` = `coord.stop()` only (leave the queue
loaded) so a later `playlist_play`/resume can pick it back up. (Maintainer decision.)

**`engine` key everywhere**: all control tools return the `engine` discriminator
(`native_queue` vs `worker`) consistently — Flight 1 left it absent from stop/status.

**Q6 = auto-resume (snapshot/restore), start-of-track**: `say`/`play_url` on an active
queue snapshot `(queue index, play_mode, was-playing)`, play the clip, block until
clip-end via `_wait_until_stopped` (already used by `say`; extend to `play_url` —
this changes `play_url`'s return-immediately contract, documented), then restore with
`play_from_queue(index)` + restore `play_mode`. **No `seek`** (start-of-track). Mechanism
premises are empirical → **Leg 3 hard-gate spike** before Leg 4 locks it.

**`say("all", ...)` is out of auto-resume scope (documented limitation)**: `_say_all`
unjoins every speaker (destroys the group) and leaves them ungrouped; a queue playing
on that group is lost and there is no group to restore to. Leg 4 documents this; it
does NOT attempt group reconstruction. Single-coordinator `say`/`play_url` is the
auto-resume path.

**Worker path is untouched by auto-resume**: auto-resume only runs on the native-queue
path (no `_sessions` entry). If a worker session is active, `play_uri` trips the worker's
existing takeover detection and the worker exits cleanly — unchanged behavior, no
interaction with the resumer.

**Cache-flush parity**: inject an `invalidate_speakers_cache: Callable[[], None]`
callback into `PlaylistManager` (alongside `resolve_coordinator`); the queue retry calls
it before re-resolving (mirrors the controller's `_speakers_ts = 0.0`) so a stale
coordinator forces re-discovery. While here, drop the now-unused return of
`_play_from_queue_with_stale_coord_retry` (→ `None`).

**`playlists.py` reads live state directly**: `_track_state` lives in `controller.py`
and is not exported; the no-session `status` reads `coord.get_current_transport_info()`
+ `coord.get_current_track_info()` directly (returning `artist`/`album`, not the
unreliable `title`).

### Prerequisites
- [ ] Live Sonos hardware on LAN + external HTTP MP3 URLs (Leg 3 spike + Leg 5 reap HAT)
- [ ] Flight 1 merged to `main` (done); `.venv` active; suite green (41 tests)

### Pre-Flight Checklist
- [x] All open questions resolved — Q6 mechanism resolved by Leg 3 gate by design;
  post-reap identity is a confirm-acceptable documentation item
- [x] Design decisions documented
- [ ] Prerequisites verified — live hardware confirmed at Leg 3 spike start
- [x] Validation approach defined
- [x] Legs defined

---

## In-Flight

### Technical Approach
1. Legs 1 + 2 are autonomous, hardware-free (live-state control surface + the
   hygiene/cleanup backlog) and can land first.
2. Leg 3 is a hard-gate HAT spike that resolves the auto-resume mechanism on
   hardware; Leg 4 (auto-resume impl) does not start until it lands.
3. Leg 5 verifies: pytest for the new logic + a manual reap+respawn HAT.

### Checkpoints
- [ ] `status`/`next`/`previous`/`stop` drive a queue-only speaker (no session) — tested vs `SoCoFake`
- [ ] Hygiene backlog cleared; suite green with new tests
- [ ] Leg 3 gate: snapshot/restore + clip-end detection proven on hardware
- [ ] `say`/`play_url` resume the queue after the clip (Q6)
- [ ] Manual HAT: kill MCP → respawn → control tools drive the live queue (Q4)

### Adaptation Criteria
**Divert if**:
- Leg 3 shows `play_uri` does not preserve the queue or position can't be restored
  reliably → fall back to "define + document interrupt-only" for Q6 and re-scope.

**Acceptable variations**:
- Clip-end detection mechanism (duration vs poll) — implementer's call per Leg 3 finding.
- Whether the resumer reuses the worker engine's polling pattern or a lighter timer.

### Legs
1. `stateless-control-surface` *(completed)* — no-session `status`/`next`/`previous`/`stop` drive
   live coordinator state (`get_current_transport_info`/`get_current_track_info`,
   `coord.next()/previous()/stop()`); `status` returns `artist`/`album` (not `title`);
   `engine` key everywhere. `stop` keeps the queue (no `clear_queue`). Worker path
   unchanged. Hardware-free tests via `SoCoFake` — extend the fake with `artist`/`album`
   fields and `next()`/`previous()` call-recording so tests assert the UPnP command issued. (Q4)
2. `retry-cache-flush-and-cleanup` *(completed)* — inject `invalidate_speakers_cache: Callable[[],None]`;
   flush in the queue retry; remove dead code (`_session_for`, drop unused retry return);
   add missing tests (`play_mode`-set-before-`play_from_queue` ordering, `status()`
   no-session, `SoCoSlaveException` retry forces re-resolution).
3. `takeover-spike` *(hard gate, HAT — PASSED)* — on hardware, confirm: (a) `play_uri` (clip)
   preserves the loaded queue; (b) `play_from_queue(index)` works on a STOPPED
   coordinator whose source was changed to the clip URL; (c) the 1-based
   `playlist_position` → 0-based `play_from_queue(index)` off-by-one; (d) clip-end is
   detectable via `_wait_until_stopped`; (e) `play_mode` snapshot/restore. (No seek —
   start-of-track.) **No Leg 4 until this lands.** (Q6 mechanism)
4. `queue-aware-takeover` *(completed)* — implement snapshot `(index, play_mode, was-playing)` →
   clip → block via `_wait_until_stopped` (extend `play_url` to block too) →
   `play_from_queue(index)` + restore `play_mode`, for single-coordinator `say`/`play_url`.
   Document the takeover contract (incl. `play_url`'s changed blocking behavior), the
   `say("all")` group limitation, and grouping (decision-level; README prose is Flight 3). (Q6)
5. `verify-integration` — pytest for the control surface + snapshot/restore logic;
   manual reap+respawn HAT (kill MCP, respawn, drive the live queue).
6. `hat-alignment` *(optional)* — guided live-hardware session for the full
   reap+respawn + takeover-resume flow.

## Verification
- **Automated (local pytest, mocked SoCo)**: live-state control surface (status/next/
  previous/stop no-session), cache-flush retry, snapshot/restore logic, `engine` key.
- **Manual HAT**: Leg 3 spike (auto-resume mechanism) and Leg 5 (reap+respawn control;
  say/play_url resume) on live speakers. No behavior-test specs.
