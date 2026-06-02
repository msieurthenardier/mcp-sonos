# Leg: queue-metadata-checkpoint

**Status**: completed
**Flight**: [Native Queue Playback Path](../flight.md)

## Objective
Empirically determine, on live Sonos hardware, whether `add_multiple_to_queue`
carries human-readable titles for bare external HTTP MP3 URLs — the load-bearing
unknown that gates the rest of the flight.

## Context
- Hard gate: no later legs start until this lands (flight Design Decisions).
- No queue code exists yet in `mcp_sonos/`; this is an exploratory SoCo spike run
  directly against a speaker, not implementation of the tool path.
- Resolves flight Open Question (metadata) and confirms the pre-decided
  `play_from_queue` stale-coord wrap (DD) is actually needed.

## Inputs
- Live Sonos speaker reachable on the LAN (IP or discoverable).
- 2–3 reachable external HTTP MP3 URLs.
- `.venv` with SoCo (0.31.0) installed.

## Outputs
- A recorded finding in the flight log: titles render as-is? or explicit DIDL
  object required? plus the stale-coord observation.
- No committed source changes (throwaway spike script lives outside the repo tree).

## Acceptance Criteria
- [x] Bulk-enqueue of ≥2 external MP3 URLs via `add_multiple_to_queue` succeeds
      — only with DIDL objects; bare URL strings raise `AttributeError`
- [x] Determined title behavior — see finding; filename-derived titles always
      render in `get_queue`; custom DIDL titles are inconsistent (Leg 3 to pin).
      Sonos app display de-scoped by maintainer (shows empty for injected items)
- [x] Determined `play_from_queue` shows no stale-coordinator symptom across runs
      on the coordinator; precautionary retry wrap retained as insurance
- [x] Multi-track native advancement confirmed by ear (track 1 → track 2 with no
      MCP involvement); finding recorded in flight log; gate decision = PROCEED

## Verification Steps
1. Confirm speaker target + test URLs (gathered interactively).
2. Run the spike script (provided by the Flight Director) against the speaker.
3. Read back queue titles + current-track info from the script output.
4. Open the Sonos app and observe whether the enqueued tracks show titles.
5. Report observations to the Flight Director, who records the finding and the
   gate decision (proceed / DIVERT).

## Edge Cases
- **No titles as-is**: retry with an explicit `DidlMusicTrack`/DIDL object; if
  that works, the queue path must build DIDL items (feeds Leg 3 design).
- **Stale coordinator**: if `play_from_queue` raises on a follower or targets the
  wrong coordinator, confirm the retry-wrap DD; resolve coordinator first.

## Files Affected
- None in the repo. Spike script is throwaway (kept outside the project tree).
