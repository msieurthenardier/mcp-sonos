# Leg: hardware-dj-run

**Status**: completed
**Flight**: [DJ Voice Segments in Playlists](../flight.md)

## Objective
Run leg 1's `dj` smoke scenario unattended against the real Sonos household,
at low volume, with the speaker's prior volume restored afterwards. Fix
anything the run surfaces.

## Context
- DD-8: the hardware verification is the `dj` scenario of
  `playlist_smoke.py`, selected by argv. The operator is asleep and
  authorized a fully autonomous run. Their listening check moves to the
  morning.
- Target: speaker **Kitchen**. At planning time (2026-10-10, `list_speakers`)
  it is a standalone coordinator at 192.168.86.53, volume 22. The other
  four speakers are grouped under Fireplace Room. Playing on Kitchen with the
  default `detach=True` touches no other group.
- The leg 1 flight-log entry lists anything the hardware run should watch
  for. Read it first.
- Prior lesson (M04 F02 debrief): a hardware leg may surface a defect that
  needs a hardening fix. Fixes made in this leg carry unit tests. If a fix
  would be a design change, stop and report it instead.

## Inputs
- Leg 1 landed: `playlist_smoke.py dj` exists and honors `SMOKE_SPEAKER` /
  `SMOKE_VOLUME`, and the unit suite is green.
- The Sonos household is reachable from this host, and the Windows Firewall
  rule "WSL-Sonos-Audio" (TCP 8000-8999) is in place.

## Outputs
- A hardware-run record in the flight log: command, exit code, the key
  observations (current item kinds, the `now_playing` URI/state during each
  voice item), and the Kitchen volume before and after.
- Code fixes plus tests, only if the run surfaces a defect.

## Acceptance Criteria
- [ ] Pre-run probe: `.venv/bin/python discovery_smoke.py --runs 1` (or the
      `list_speakers` tool) finds Kitchen. Record Kitchen's volume.
- [ ] `SMOKE_SPEAKER=Kitchen SMOKE_VOLUME=10 timeout 600 .venv/bin/python playlist_smoke.py dj`
      exits 0. Output shows:
      - the voice item became `current_item` and `now_playing` reported
        `PLAYING` with its hosted `.wav` URI;
      - the advance to the next track;
      - the live-appended voice item became `current_item` and played.
- [ ] After the run, Kitchen's volume equals the recorded pre-run value, and
      no playlist session is left running (`playlist_status` for Kitchen
      reports not running, or `now_playing` reports `STOPPED`).
- [ ] If any step failed and a fix was made, the unit suite is green and
      the smoke run is repeated to exit 0. Total hardware attempts stay at
      3 or fewer.

## Verification Steps
- Shell output of the probe, the smoke command, and the exit code.
- A `now_playing` / `list_speakers` read after the run for state and volume.

## Implementation Guidance
1. Probe the household. If Kitchen is unreachable, retry once after 30 s.
   If it is still unreachable, set `[BLOCKED:hardware-unreachable]` and stop.
2. Record Kitchen's pre-run volume.
3. Run the smoke command above. Capture the full output to
   `/tmp/claude-1000/-home-cprch-projects-mcp-sonos/09563edd-da95-40c5-99a8-fe73f3d20b5c/scratchpad/dj-smoke-{n}.log`
   (outside the repo; never commit it).
4. On failure, diagnose from the logs. Distinguish a harness or apparatus
   fault (timing in the smoke script) from a product fault, and fix the
   right one. Product fixes need a unit test. Re-run, up to 3 attempts in
   total.
5. In a `finally`, or manually if the script crashed before its own
   `finally`, make sure Kitchen's volume is restored and playback is
   stopped.
6. Append the run record to the flight log.

## Edge Cases
- **Voice item ends before `PLAYING` is observed** (short clip): this is the
  flight's named residual risk. If it happens, prefer a longer DJ text in
  the scenario over loosening the assertion, and log it as an anomaly.
- **External tracks unreachable**: `_smoke_common.select_track_pool`
  already probes. If no pool is reachable, report it as an environment
  block, not a product failure.
- **Fireplace Room group playing something**: not touched. Kitchen is
  standalone.

## Files Affected
- None expected. If the run finds a defect: `mcp_sonos/playlists.py` and/or
  `playlist_smoke.py`, plus tests.

---

## Post-Completion
Completion steps (status transitions, flight-log update, checking off in the
parent flight, and commit) are Flight Control protocol, driven by the
execution workflow. They are not repeated here.
