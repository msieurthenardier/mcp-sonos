# Flight Briefing: DJ Voice Segments in Playlists

**Date**: 2026-10-10
**Flight**: [DJ Voice Segments in Playlists](flight.md)
**Status**: Flight is ready for execution

## Mission Context
Sortie 01 (no parent mission). Charter outcome: the agent can put spoken DJ
segments (plain text, synthesized server-side) anywhere in a playlist, and
`playlist_play` plays songs and voice in order with no further calls.

## Objective
Add a voice item kind to playlists, make the worker pick up items appended
during playback, fix the shuffled-status and previous-at-start defects that
this feature exposes, verify on hardware, then merge and release 0.6.0.

## Key Decisions
- `text` as the either/or alternative to `url` on `playlist_add` /
  `playlist_add_many`; no new tool (DD-1).
- Eager synthesis at add time through an injected `synthesize_voice` callable;
  validate everything before synthesizing anything (DD-2).
- Routing unchanged: voice URLs are MCP-hosted → worker engine (DD-3).
- Live append via `scheduled_count`, with the end-of-order check, item
  snapshot, and session deregistration in one `_lock` block (DD-5).
- Shuffle is allowed and is the agent's choice (DD-6).
- `current_playlist_index` fixes shuffled `status()` (DD-9); previous-at-0/1
  fix (DD-10).

## Risks and Mitigations
| Risk | Mitigation |
|------|------------|
| Short voice clip ends before PLAYING is observed | `dj` smoke asserts PLAYING with `uri == item.url` while the voice item is current |
| Deadlock from the new worker lock block | Block calls no `_lock`-taking helpers (spec rule); unit tests with real threads |
| Late `finally` deregisters a newer session | Both pops keep the `cur is session` guard |
| Overnight hardware run disturbs the household | Target speaker at volume ≈10, restored afterwards; run kept short |
| Firewall rule missing → silent STOPPED | Prerequisite check at leg 2 start |

## Legs Overview
1. `voice-items` — item kind, synthesis DI, live append, DD-9/DD-10 fixes,
   unit tests, `dj` smoke scenario, docs, version 0.6.0 — high complexity
2. `hardware-dj-run` — unattended low-volume `dj` smoke on the real household;
   fix anything found — low/medium complexity

## Environment Requirements
`.venv` with `.[dev]`; Sonos household reachable on the LAN for leg 2
(Windows Firewall rule "WSL-Sonos-Audio" in place).

## Success Criteria
The charter's four criteria. Audible confirmation is deferred to the
operator's morning check-in.
