# Mission: Resilient Queue-Backed Playback

**Status**: completed

## Outcome
A multi-track playlist of externally-hosted HTTP MP3s, once started, keeps
playing on the Sonos household even after the MCP server is reaped for
inactivity. Today the playlist is driven by an in-process worker thread
(`mcp_sonos/playlists.py`) that issues one `play_uri` per track and polls
transport state at 2 Hz; when the agentic host reaps the MCP, the worker
dies and playback stops at the current track. After this mission, the
common case — queuing a list of web MP3s (e.g. song links from a blog) and
walking away — is handed to Sonos's **native queue**, which advances
track-to-track speaker-side with zero host involvement. The MCP becomes
optional during playback: it can be reaped and respawned freely, and
`playlist_status`/`next`/`previous`/`stop` work against live speaker state
when it comes back.

## Context
The MCP is driven by an agentic system that reaps the server on inactivity
and respawns it on demand. The current playlist engine is fundamentally
incompatible with that lifecycle: it keeps the entire play sequence in
process memory and only ever tells the speaker about one track at a time,
so process death = playback death.

Sonos exposes two native mechanisms SoCo already wraps:
- **The queue** (per-coordinator, transport-level): `add_multiple_to_queue`,
  `play_from_queue`, `clear_queue`, `queue_size`, native `next()`/`previous()`,
  and `play_mode` (`NORMAL`/`SHUFFLE`/`SHUFFLE_NOREPEAT`/`REPEAT_ALL`/`REPEAT_ONE`).
  Sonos advances the queue itself — no worker, no polling.
- **Sonos Playlists** (persistent, household-stored, visible in the app):
  `create_sonos_playlist`, `get_sonos_playlists`, etc.

This mission adopts the **queue** for the survive-reaping path. Native Sonos
Playlists (persistence/library) are explicitly **deferred** — see Open
Questions and the existing README Roadmap "Playlist persistence" item.

**Hard boundary discovered during design.** A queue item only survives
reaping if Sonos can fetch it without the MCP. The audio HTTP host
(`mcp_sonos/audio_host.py`) is a daemon thread *inside* the MCP process, so
any item it serves dies when the process is reaped:

| Content | URL source | Survives reap? |
|---|---|---|
| Internet/music HTTP MP3s | external host | yes |
| TTS (`say`) | MCP audio host | no — but `say` re-wakes the MCP, so N/A |
| `play_file` staged files | MCP audio host | no |
| Live streams | external | already fine once started |

The maintainer's immediate need is the external-web-MP3 case. Local-file
playlists are a known, accepted limitation (would require decoupling the
audio host into a persistent sidecar — out of scope here).

## Success Criteria

- [ ] Q1 — A playlist of all-external HTTP MP3 URLs started via `playlist_play`
  continues advancing track-to-track after the MCP server process is killed
  and **not** respawned (verified on live hardware)
- [ ] Q2 — Arbitrary external HTTP MP3 URLs can be bulk-enqueued **with
  titles** that render correctly in `playlist_status` and the Sonos app.
  (Whether SoCo's `add_multiple_to_queue` carries title/DIDL metadata for
  bare MP3s is the load-bearing unknown — first checkpoint of Flight 1.)
- [ ] Q3 — Shuffle and normal ordering are handled speaker-side; the queue
  path no longer relies on the in-process permutation logic
  (`playlists.py:227`). (Native `play_mode` is the intended mechanism.)
- [ ] Q4 — After an MCP reap+respawn, `playlist_status`, `playlist_next`,
  `playlist_previous`, and `playlist_stop` operate correctly against live
  speaker state with no reliance on the lost in-RAM `_sessions` entry
- [ ] Q5 — A playlist containing any MCP-hosted (local-file) URL transparently
  falls back to the existing worker-thread engine; that path's behavior is
  unchanged
- [ ] Q6 — `say`/`play_url` interaction with an active queue is defined and
  documented (interrupt vs. resume vs. end), and grouping behavior of the
  queue path is documented
- [x] Q7 — A reader or agent can correctly understand and drive the queue
  path from the docs alone: the README playlist section + limitations,
  CLAUDE.md architecture notes, and the agent system prompt all describe the
  queue-backed behavior (including reap-survival and the local-file
  fallback), and a smoke test exercises the queue path
  — **Flight 3** (README/CLAUDE.md/system-prompt/.env + `reap_smoke.py`)

## Verification Approach
- **Automated tests (regular pytest, run locally)** cover everything the MCP
  itself owns: the external-vs-MCP-hosted URL classifier, queue-vs-worker
  routing, the Q5 fallback decision, and the Q4 stateless reconstruction of
  `status`/`next`/`previous`/`stop` from live speaker state. These run
  hardware-free with mocked SoCo, reusing the M1 DI test scaffolding.
- **Hardware acceptance testing (HAT) is completely manual.** The criteria
  whose only honest observable lives in Sonos firmware — Q1 (playback
  survives an MCP reap), Q2 (titles render in the Sonos app), and the live
  half of Q4 (control after reap+respawn) — are verified by hand against
  real speakers via `smoke_test.py` / `playlist_smoke.py`. No automated
  behavior-test specs are authored for this mission.

## Stakeholders
Maintainer (msieurthenardier). Self-deployed on home LAN, driven by an
agentic host that reaps the MCP on inactivity. No external users.

## Constraints
- **Hybrid, not replacement.** The native-queue path is for all-external
  playlists; the existing worker-thread engine stays as the fallback for
  playlists containing MCP-hosted URLs (maintainer decision). Do not remove
  the worker engine.
- **Defer native Sonos Playlists.** Persistence/library is out of scope;
  keep the named-playlist definitions in-memory as today.
- Anything touching groups must go through `_coordinator_of` /
  `_group_members_of` (CLAUDE.md invariant).
- Cross-cutting input validation stays centralized (`_urls.py` pattern);
  the external-vs-MCP-hosted classifier is a candidate for that module.
- The tool surface (`playlist_*` names) is the contract with the agent —
  re-back it with the queue rather than renaming, to avoid churning the
  system prompt unless a leg justifies it.

## Environment Requirements
- Existing local Python venv at `<repo-root>/.venv`
- Live Sonos hardware on LAN for smoke-test verification (`smoke_test.py`,
  `playlist_smoke.py`) — required for Q1/Q2, which cannot be faked
- A reachable set of external HTTP MP3 URLs for queue verification
- WSL2 mirrored networking + the `WSL-Sonos-Audio` firewall rule (already
  in place) for the worker-fallback path's audio host
- No CI to satisfy

## Open Questions
- Native Sonos Playlists for persistence/library — deferred this mission;
  revisit as a follow-up tied to the README Roadmap item.
- How `add_multiple_to_queue` handles title/DIDL metadata for bare HTTP
  MP3s (SoCo may need an explicit DIDL object) — to be resolved as Flight 1's
  first checkpoint, not assumed.
- Post-reap identity: after a respawn there's no session memory, so
  `status`/`next` read live speaker state and cannot perfectly distinguish
  "our playlist" from unrelated playback. Define acceptable semantics in
  the flight.
- Stale-coordinator divergence on queue calls: Mission 01 found that SoCo's
  cached coordinator can diverge from live firmware state, addressed for
  `play_uri` with the `_play_uri_with_stale_coord_retry` pattern
  (`controller.py`). The new queue operations (`add_multiple_to_queue`,
  `play_from_queue`, native `next`/`previous`) may hit the same divergence —
  Flight 1 should decide whether the queue path needs equivalent
  stale-coordinator retry handling.

## Known Issues
- [x] Interim contract gap (Flight 1 → **resolved by Flight 2**): after a queue-backed
  `playlist_play`, `playlist_stop`/`playlist_status` returned `{"running": false}` while
  the speaker was audibly playing. Flight 2's stateless control surface now drives live
  coordinator state (status/next/previous/stop), verified on hardware via reap+respawn HAT.

## Flights

> **Note:** Tentative suggestions, not commitments. Flights are planned and
> created one at a time as work progresses. This list will evolve.

- [x] Flight 1: Native queue playback path — URL classifier (external vs
  MCP-hosted), queue-backed `playlist_play` with titles + native `play_mode`,
  worker-thread fallback, and the `add_multiple_to_queue` metadata checkpoint
  — **completed** (Q1/Q2/Q3/Q5 + Q6-partial; Q1 reap proven on hardware; debriefed)
- [x] Flight 2: Reap-resilient control surface — stateless
  `playlist_status`/`next`/`previous`/`stop` against live speaker state, plus
  `say`/`play_url` takeover and grouping semantics
  — **landed** (Q4 + Q6; reap+respawn control & say-resume mid-track proven on hardware)
- [x] Flight 3: Documentation + smoke coverage — README/CLAUDE.md/system
  prompt alignment and a queue-path smoke test
  — **landed** (Q7; docs across README/CLAUDE.md/system-prompt/.env + reap-survival smoke)
