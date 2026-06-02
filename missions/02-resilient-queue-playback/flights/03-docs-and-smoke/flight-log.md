# Flight Log: Documentation + Smoke Coverage

**Flight**: [Documentation + Smoke Coverage](flight.md)

## Summary
Planned and design-reviewed. Status `ready`. Execution not yet started.

### Design review (Architect)
Verdict: **approve with changes** — accuracy fixes folded into the spec before `ready`:
- [high] `play_url` docstring (controller.py ~178-180) still says "start of the interrupted
  track" (pre-mid-track-pivot) — must be corrected to mid-track best-effort. Added to Leg 2.
- [high] `say("all")` leaves every speaker **ungrouped** after the clip (not just "destroys
  the group") — doc framing sharpened.
- [med] `status().title` is present-but-unreliable (firmware returns URI stem/blank) — don't
  claim it's absent; prefer artist/album.
- [med] Missing doc item: `next`/`previous` swallow `SoCoSlaveException` (no retry) — added.
- Suggestions folded: stale README Roadmap "say snapshot/restore" item (now done); System
  prompt items ~8/11 manual-resume dance obsolete for native queue; two-phase smoke
  (`--load`/`--control`) since one process can't reap itself; root-level script not collected
  by pytest (`testpaths=["tests"]`). Residual start-of-track wording located precisely
  (strike Leg 4 Objective + Leg 5 criterion; keep the fallback-description lines).

---

## Leg Progress

### Leg 1 — docs (landed)

**Status**: landed
**Files changed**: `README.md`, `CLAUDE.md`, `.env.example`

**Summary**: Documented the Flight 1+2 queue work across all three
doc files. Key changes:

- `README.md`:
  - `### Playlist limitations` rewritten for the two-engine reality
    (native queue vs worker, Sonos-app empty-queue display artefact,
    post-reap identity).
  - *What it does* block adds the two-engine/engine-key paragraph.
  - *Configuration* table adds `PLAY_URL_RESUME_TIMEOUT_SECONDS`
    (default 3600).
  - *Architecture* adds `playlists.py`, two-engine routing summary,
    and `say`/`play_url` mid-track best-effort resume summary.
  - *System prompt* items 8 and 11 corrected: native-queue auto-resumes
    mid-track; manual capture/replay dance is now scoped to worker
    engine / no active queue only. Item 10 adds engine-key and
    reap-survival guidance.
  - Roadmap "say with snapshot/restore" marked done with implementation
    reference.
  - TTS/`say` limitations section updated: auto-resume behaviour for
    native queue; `say("all")` leaves-ungrouped caveat added.

- `CLAUDE.md`:
  - New subsections under `playlists.py`: Two-engine architecture +
    routing rule; PlaylistManager DI params; engine discriminator;
    `QUEUE_PARENT_ID = "A:TRACKS"` with audit-trail pointer to Leg 1
    (Flight 1) `parent_id="-1"` finding; Caveats block (`status().title`
    unreliable, `say("all")` state-destructive, `next`/`previous`
    best-effort no retry, `play_url` blocks).

- `.env.example`:
  - Added commented `PLAY_URL_RESUME_TIMEOUT_SECONDS=3600` entry after
    `AUDIO_PORT`, matching existing comment style.

**pytest**: 63 passed (docs-only, no behavior change).

---

### Leg 2 — smoke-and-hygiene (landed)

**Status**: landed
**Files changed**: `reap_smoke.py` (new), `mcp_sonos/controller.py`, `mcp_sonos/playlists.py`,
`missions/.../flights/02-reap-resilient-control/legs/04-queue-aware-takeover.md`,
`missions/.../flights/02-reap-resilient-control/legs/05-verify-integration.md`

**Summary**: Committed the reap-survival smoke script, applied source hygiene, and struck
the residual stale "start-of-track" wording from the Flight 2 leg artifacts.

- `reap_smoke.py` (repo root): two-phase argparse script (`--load` / `--control`). `--load`
  creates an all-external playlist (3 SoundHelix MP3s), calls `playlist_play`, asserts
  `engine == "native_queue"`, prints, then exits — the process exit is the reap. `--control`
  is a fresh process: calls `playlist_status` (asserts `engine == "native_queue"` and live
  state present), `playlist_next`, `playlist_status`, `playlist_stop`, then deletes the
  playlist. Fails fast with a clear message if no speakers are reachable. Uses
  `os.environ.setdefault("SONOS_IPS", "192.168.1.51,...")` — same placeholder IPs as
  `queue_smoke.py`. Root-level placement confirmed: pytest `testpaths=["tests"]` does not
  collect it.

- `mcp_sonos/controller.py` (additive only):
  - `play_url` docstring: "start of the interrupted track" → "resumes mid-track (best-effort;
    falls back to start-of-track if the host rejects the seek)".
  - `# NOTE:` at `coord_holder`: explains the mutable single-cell list box pattern used so
    the closure can hand back a replaced coordinator after a stale-coord retry.
  - `# NOTE:` at `coord.play_mode = saved_play_mode`: documents that `play_mode` is not
    restored if `play_from_queue` itself fails — intentional, no queue position to restore to.

- `mcp_sonos/playlists.py` (additive only):
  - `# NOTE:` at `next_track` and `previous_track` no-session branches: swallows
    `SoCoSlaveException` with no stale-coord retry (unlike `say()`) — best-effort, advance
    may be silently lost during group churn.
  - `# NOTE:` at `QUEUE_PARENT_ID`: audit-trail pointer — Flight 1 hardware finding that
    `parent_id="-1"` causes firmware to discard title metadata.

- Flight 2 artifact wording corrections (artifact-only, no code):
  - `legs/04-queue-aware-takeover.md` Objective: "resume the queue at start-of-track" →
    "resume the queue mid-track (best-effort; falls back to start-of-track if the host
    rejects the seek)".
  - `legs/05-verify-integration.md` Q6 criterion: "queue resumes at start-of-track" →
    "queue resumes mid-track, best-effort (falls back to start-of-track if the host rejects
    the seek)". Fallback-description lines untouched.

**pytest**: 63 passed (root script not collected; source edits are comments/docstring only).

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

_None yet._
