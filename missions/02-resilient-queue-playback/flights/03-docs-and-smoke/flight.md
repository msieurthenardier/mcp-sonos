# Flight: Documentation + Smoke Coverage

**Status**: completed
**Mission**: [Resilient Queue-Backed Playback](../../mission.md)

## Contributing to Criteria
- [ ] Q7 — A reader or agent can correctly understand and drive the queue path from the
  docs alone: README playlist section + limitations, CLAUDE.md architecture notes, and the
  agent system prompt describe the queue-backed behavior (reap-survival + fallback), and a
  smoke test exercises the queue path

## Pre-Flight

### Objective
Close the mission by documenting the Flight 1+2 queue work everywhere an agent or reader
looks (README, CLAUDE.md, agent system prompt, `.env.example`), committing a reap-survival
smoke script, and clearing the small Flight 2 debrief hygiene items (source `# NOTE:`
comments + residual "start-of-track" wording in the Flight 2 artifacts).

### Open Questions
_None — behavior is already proven (Flight 1+2 HAT); this flight is docs + a smoke script +
comments. No hardware gate._

### Design Decisions
- **No behavior-test spec.** The mission's Verification Approach stands: HAT is manual, no
  behavior-test specs. Q7's smoke is a plain operator-runnable script.
- **Agent system prompt lives in the README** (`## System prompt for your agent`) — update
  it there, not a separate file.
- **Docs reflect the two-engine reality** (claims verified against code in design review):
  - native queue (all-external, survives reap) vs worker fallback (MCP-hosted / no host-port);
    the `engine` discriminator (`native_queue`/`worker`).
  - `say`/`play_url` snapshot+resume is **mid-track, best-effort** — `play_from_queue(index)`
    then `seek(position)`; falls back to start-of-track ONLY if the host rejects HTTP range.
    (Frame it this way everywhere; do NOT say "start of track" unqualified.)
  - **Stale `play_url` docstring** (`controller.py` ~line 178-180) still says "start of the
    interrupted track" — pre-pivot; must be corrected to the mid-track-best-effort framing.
  - `say("all")` **leaves every speaker ungrouped after the clip** (unjoin → partymode →
    play → unjoin) — state-destructive, not "best-effort"; no group reconstruction.
  - `play_url` now **blocks** until clip-end (cap `PLAY_URL_RESUME_TIMEOUT_SECONDS`, default 3600).
  - `status().title` is **unreliable for queued items** — firmware may return the URI stem or
    blank; prefer `artist`/`album` (do NOT claim `title` is absent — it's present but unreliable).
  - `next`/`previous` no-session are **best-effort**: a `SoCoSlaveException` is swallowed (no
    stale-coord retry, unlike `say`) so an advance during group churn may be silently lost.
  - post-reap identity limitation (control tools act on whatever the coordinator is playing).
  - README **Roadmap** has a now-stale "say with snapshot/restore" item → remove/mark done.
  - README **System prompt** items ~8/11 describe a manual capture/`play_url`-again resume
    dance — obsolete for the native-queue path (it auto-resumes); update to distinguish
    native-queue (auto) vs worker/no-queue (manual).
- **Code NOTEs included** (operator decision): `# NOTE:` at the `coord_holder` site, the
  `play_mode`-restore best-effort (not restored if `play_from_queue` itself fails), and
  `next`/`previous` no-session (no stale-coord retry); plus a `QUEUE_PARENT_ID` audit-trail
  pointer to the Leg 1 finding; plus the `play_url` docstring correction above.

### Prerequisites
- [ ] Flights 1 + 2 merged to `main` (done); `.venv` active; suite green (63 tests)

### Pre-Flight Checklist
- [x] All open questions resolved (none)
- [x] Design decisions documented
- [ ] Prerequisites verified
- [x] Validation approach defined
- [x] Legs defined

## In-Flight

### Technical Approach
Both legs are autonomous and hardware-free to author. The smoke script is operator-runnable
against hardware but its behavior is already HAT-proven; committing a correct script
satisfies Q7. Single review + commit at flight end (agentic-workflow default).

### Checkpoints
- [ ] README accurately describes queue-backed playback + limitations + the updated system prompt
- [ ] CLAUDE.md documents the two-engine architecture + DI params + code-pattern notes
- [ ] `.env.example` includes `PLAY_URL_RESUME_TIMEOUT_SECONDS`
- [ ] Reap-survival smoke script committed; suite green
- [ ] Flight 2 artifact "start-of-track" wording corrected; `# NOTE:` comments added

### Adaptation Criteria
**Divert if**: writing the docs surfaces a behavior that contradicts the implementation
(i.e., a real bug) → stop and raise it rather than documenting around it.

**Acceptable variations**: reap-survival smoke as a new script or an extension of
`queue_smoke.py` — implementer's call; doc section placement within README/CLAUDE.md.

### Legs
1. `docs` *(completed)* (doc files only) — README: rewrite `### Playlist limitations` for the two-engine/
   reap reality; add queue to *What it does* / *Tools* / *Architecture*; add
   `PLAY_URL_RESUME_TIMEOUT_SECONDS` to *Configuration*; update *System prompt for your agent*
   (engine discriminator, reap-survival control, `play_url` blocking, AND fix the obsolete
   manual-resume dance in items ~8/11 → native-queue auto-resumes); remove/mark-done the stale
   Roadmap "say with snapshot/restore" item. CLAUDE.md: two-engine architecture, `PlaylistManager`
   DI params (`host_ip`/`audio_port`/`resolve_coordinator`/`invalidate_speakers_cache`), `engine`
   key, `QUEUE_PARENT_ID` audit pointer, `status().title` caveat (present-but-unreliable),
   `say("all")` leaves-ungrouped, `next`/`previous` best-effort no-retry, post-reap identity.
   `.env.example`: add `PLAY_URL_RESUME_TIMEOUT_SECONDS`. (Q7 docs)
2. `smoke-and-hygiene` *(completed)* (source + smoke + artifacts) — commit a **two-phase**
   reap-survival smoke (`reap_smoke.py --load` loads via `playlist_play` then exits = the reap;
   `reap_smoke.py --control` is a fresh process that drives `playlist_status`/`next`/`stop` and
   asserts `engine == "native_queue"`; `SONOS_IPS` via `os.environ.setdefault` with the same
   placeholder IPs as the existing smokes; cleanup; fail-fast if no hardware; lives at repo root
   so pytest `testpaths=["tests"]` won't collect it). Source edits: the `play_url` docstring
   correction (controller.py) + `# NOTE:` comments (controller.py `coord_holder` & `play_mode`-restore;
   playlists.py `next`/`previous` no-session; `QUEUE_PARENT_ID` audit pointer). Artifact fix:
   strike the stale "start-of-track" lines — Flight 2 `legs/04-...md` **Objective** ("resume the
   queue at start-of-track") and `legs/05-...md` **objective/criterion** — but do NOT touch the
   *fallback*-description lines (those correctly describe start-of-track as the seek fallback).
   Suite stays green (63).

## Verification
- **Automated**: `pytest` stays green (63 tests; no behavior change expected — docs + comments
  + a new uncommitted-to-suite smoke script).
- **Manual (optional)**: operator can run the reap-survival smoke against live hardware; not
  required for landing since the behavior is already HAT-proven in Flights 1–2.
