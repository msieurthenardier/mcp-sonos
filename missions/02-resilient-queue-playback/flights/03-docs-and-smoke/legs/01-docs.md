# Leg: docs

**Status**: completed
**Flight**: [Documentation + Smoke Coverage](../flight.md)

## Objective
Document the Flight 1+2 queue work in the three places an agent/reader looks — README,
CLAUDE.md, and the README's agent system-prompt section — plus `.env.example`, so the
queue-backed behavior + limitations can be understood and driven from docs alone. (Q7)

## Context
- Flights 1+2 added: native-queue playback (all-external playlists, survives MCP reap),
  worker fallback (MCP-hosted URLs), the `engine` discriminator, stateless control after
  reap, and `say`/`play_url` snapshot+resume. NONE of this is in the README today.
- All doc claims below were verified against code in the flight design review — use them
  verbatim in framing; do not soften or re-derive.
- Doc-files only (README.md, CLAUDE.md, .env.example). Source comments + smoke are Leg 2.

## Acceptance Criteria
- [x] README `### Playlist limitations` rewritten for the two-engine reality: native queue
      (all-external → survives reap, advances speaker-side) vs worker fallback (any
      MCP-hosted/local-file URL, in-process); the Sonos app shows an empty queue for
      injected items (accepted); post-reap identity (control acts on whatever the
      coordinator is playing)
- [x] README *What it does* / *Tools* / *Architecture* mention queue-backed playback + engine key
- [x] README *Configuration* documents `PLAY_URL_RESUME_TIMEOUT_SECONDS` (default 3600)
- [x] README *System prompt for your agent* updated: `engine` discriminator
      (`native_queue`/`worker`); control tools work after a reap; `say`/`play_url`
      **auto-resume** a native queue mid-track (best-effort) — and the OBSOLETE manual
      capture/`play_url`-again resume dance (items ~8/11) is corrected to say the manual
      dance is only needed for the worker engine / no active queue
- [x] README Roadmap: the stale "say with snapshot/restore" item removed or marked done
- [x] CLAUDE.md documents: the two-engine architecture + routing rule (all-external→queue,
      any MCP-hosted or no host/port→worker); `PlaylistManager` DI params
      (`host_ip`, `audio_port`, `resolve_coordinator`, `invalidate_speakers_cache`);
      the `engine` key; `QUEUE_PARENT_ID = "A:TRACKS"` with an audit-trail pointer to the
      Leg 1 (Flight 1) finding that `parent_id="-1"` loses titles
- [x] CLAUDE.md notes the caveats accurately: `status().title` is **present but unreliable**
      for queued items (firmware may return URI stem/blank) → prefer `artist`/`album`;
      `say("all")` **leaves all speakers ungrouped** after the clip (state-destructive, no
      reconstruction); `next`/`previous` no-session are best-effort (swallow `SoCoSlaveException`,
      no stale-coord retry); `play_url` now BLOCKS until clip-end
- [x] `.env.example` adds a commented `PLAY_URL_RESUME_TIMEOUT_SECONDS` entry (style matches
      the existing `HOST_IP`/`AUDIO_PORT` entries)
- [x] No doc claim contradicts the code (verify against playlists.py/controller.py while writing)

## Verification Steps
- Re-read each new/edited section against the actual code paths it describes.
- `pytest -q` still green (docs-only; no behavior change).

## Implementation Guidance
1. Read the current README.md, CLAUDE.md, .env.example and the code (playlists.py
   `play()` routing + control methods + `QUEUE_PARENT_ID`; controller.py `_with_queue_resume`,
   `say`/`_say_all`, `play_url`, `PLAY_URL_RESUME_TIMEOUT_SECONDS`).
2. Edit in place, matching each file's existing terse style and section structure.
3. Frame `say`/`play_url` resume as **mid-track, best-effort** (NOT "start of track").
4. Do NOT touch source files or the smoke scripts (Leg 2).

## Files Affected
- `README.md`, `CLAUDE.md`, `.env.example`
