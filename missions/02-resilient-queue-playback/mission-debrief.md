# Mission Debrief: Resilient Queue-Backed Playback

**Date**: 2026-06-02
**Mission**: [Resilient Queue-Backed Playback](mission.md)
**Status**: completed
**Duration**: 2026-06-01 → 2026-06-02
**Flights Completed**: 3 of 3

## Outcome Assessment

### Success Criteria Results
| Criterion | Status | Notes |
|-----------|--------|-------|
| Q1 — All-external playlist keeps advancing after MCP killed (not respawned) | ✅ met | Proven on live hardware (Flight 1 + reap HAT) via the shipped `playlist_play`→native-queue path |
| Q2 — Bulk-enqueue external MP3s **with titles** | ✅ met | DIDL recipe (`add_multiple_to_queue` + `DidlMusicTrack`, `parent_id != "-1"`); titles render in `playlist_status` |
| Q3 — Shuffle/normal ordering speaker-side (no in-process permutation) | ✅ met | Native `play_mode` (`SHUFFLE_NOREPEAT`/`NORMAL`) on the queue path |
| Q4 — Control surface works after reap+respawn (no `_sessions` reliance) | ✅ met | Stateless `status`/`next`/`previous`/`stop` on live coordinator state; reap+respawn HAT (Flight 2) |
| Q5 — MCP-hosted-URL playlist falls back to worker engine, unchanged | ✅ met | `any_mcp_hosted` routing; worker path extracted verbatim |
| Q6 — `say`/`play_url` ↔ queue defined + grouping documented | ✅ met (exceeded) | Implemented snapshot+**mid-track resume** (not just defined); `say("all")` documented as state-destructive |
| Q7 — Docs + smoke: queue path understandable/drivable from docs alone | ✅ met | README + CLAUDE.md + agent system prompt + `.env.example` + two-phase `reap_smoke.py` (Flight 3) |

### Overall Outcome
**The mission delivered its outcome in full.** A multi-track playlist of external HTTP MP3s,
once started, keeps playing on the Sonos household after the MCP is reaped — handed to Sonos's
native queue, which advances speaker-side with zero host involvement. The MCP is now optional
during playback: it can be reaped and respawned freely, and the control tools operate against
live speaker state when it returns. The hybrid design (native queue for all-external, worker
fallback for MCP-hosted/local-file URLs) was honored throughout. The goal remained the right
goal end-to-end; Q6 was over-delivered (auto-resume implemented, not merely documented).

## Flight Summary
| Flight | Status | Key Outcome |
|--------|--------|-------------|
| 1 — Native queue playback path | ✅ completed | Two-engine routing + queue-backed `playlist_play` (DIDL recipe, native `play_mode`, worker eviction); Q1/Q2/Q3/Q5 + version-reporting fix |
| 2 — Reap-resilient control surface | ✅ completed | Stateless control after reap (Q4) + `say`/`play_url` snapshot/mid-track-resume (Q6); cleared all Flight 1 debrief items |
| 3 — Documentation + smoke | ✅ completed | Q7 docs across README/CLAUDE.md/system-prompt/`.env`; `reap_smoke.py`; hygiene cleanup |

## What Went Well
1. **Hardware-gate spikes before empirical features** — the operator's pick for what most
   earned its keep. Three times (F1 metadata gate, F2 takeover gate, F2 ad-hoc seek spike) a
   throwaway HAT spike proved an undocumented Sonos/SoCo behavior *before* code was written:
   bare URLs are rejected (need DIDL); `play_uri` preserves the queue; the host honors HTTP
   range (enabling mid-track resume). Each gate converted an assumption into a verified recipe
   and prevented a debug-session-disguised-as-a-leg.
2. **The debrief→next-flight action-item loop closed every time.** Every Flight 1 debrief item
   was a Flight 2 deliverable; the Flight 1 interim Known Issue was resolved in Flight 2; the
   Flight 2 debrief items were Flight 3's backlog. No item decayed.
3. **Layered, independent review caught distinct issues** at each altitude: the flight Architect
   (e.g. the retry helper hardcoded to `play_uri`; the stale `play_url` docstring), per-leg
   design review (s.uid keying; `SoCoFake` `_track` clobber), and the independent code Reviewer
   (play_file inherits the contract). The Architect's mission verdict: a coherent, healthier
   codebase (0→63 hardware-free tests), two-engine split a sound long-term design bounded by a
   physical constraint — not an interim hack.

## What Could Be Improved
1. **SoundHelix single-point-of-failure** (medium debt): all four smoke scripts depend on
   SoundHelix MP3 URLs with no SLA — if it goes offline, all four degrade at once. Best
   addressed in `/routine-maintenance` (fallback URL or a tiny self-hosted test MP3).
2. **Doc-drift risk across three locations**: the two-engine + agent guidance spans README,
   CLAUDE.md, and the verbose 11-item system-prompt section, which can drift independently.
3. **A few low-severity carryovers**: the controller's `SoCoSlaveException` retry branch is
   still zero-coverage; firmware-empirical assumptions (`QUEUE_PARENT_ID="A:TRACKS"`,
   `play_from_queue` queue-preservation, 1-based `playlist_position`) are confirmed-once and
   not version-guarded; two divergent stale-coord retry helpers (low, documented).

## Lessons Learned
- **Technical**: A two-engine split is the right call when the divergence is a *physical*
  constraint (in-process audio host dies on reap), not a stylistic one. Firmware/3rd-party
  behaviors that aren't in the docs should be pinned by an explicit empirical gate and carry
  an audit-trail comment; they remain the highest-risk assumptions on a firmware update.
- **Process**: Conservative planning placeholders + **operator-in-loop revision** beat trying
  to settle every UX detail upfront — *because* the mechanism was gated first, the mid-track
  pivot cost ~10 lines + 3 tests. Surfacing decisions at the right moments (the operator
  caught the version-reporting bug during a debrief and insisted on the reap-survival listen)
  was rated "about right" on autonomy.
- **Domain**: Sonos's native queue is the correct substrate for survive-the-reap playback;
  the Sonos *app* won't display locally-injected queue items (accepted — the maintainer is
  intentionally moving away from the app).

## Methodology Feedback
*(improvements to Flight Control itself)*
1. **Promote "empirical/hardware spike hard-gate" to a first-class leg type.** It proved its
   value three times this mission. A named leg type with a standard shape (throwaway artifact,
   PROCEED/DIVERT criterion, recipe recorded to the flight log) would make the pattern default
   rather than ad-hoc.
2. **Reopened-leg supersession convention**: when a leg is reopened mid-flight (the mid-track
   pivot), *strike/supersede* the stale criteria rather than appending — appending left
   "start-of-track" wording that needed a later cleanup pass.
3. **Anti-doc-drift AC**: when a flight adds/changes a tool or engine behavior, make "update
   README system-prompt + CLAUDE.md architecture section" an explicit leg acceptance criterion.
4. **Return-shape consistency checklist** in the leg template (the `engine`-key-everywhere item
   landed as a post-review fix that a checklist would have caught at spec time).

## Action Items
- [ ] `/routine-maintenance` pass for post-mission health — esp. de-risk the shared SoundHelix
      smoke dependency
- [ ] Next `playlists.py`/`controller.py` change: add the `SoCoSlaveException` controller-retry
      test + a fixture asserting the 1-based→0-based `playlist_position` conversion
- [ ] Adopt the anti-doc-drift AC + reopened-leg supersession conventions on future flights
- [ ] Mission 03 candidate (deferred roadmap): native Sonos Playlists persistence — would add a
      third engine path; re-verify `QUEUE_PARENT_ID` + `play_from_queue` assumptions on current firmware
- [ ] (Methodology, mission-control repo) consider a first-class hardware-spike leg type
