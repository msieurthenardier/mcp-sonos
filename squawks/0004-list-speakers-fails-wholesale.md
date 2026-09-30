# Squawk 0004: `list_speakers` fails wholesale on one speaker's transient UPnP error

**Status**: open
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: —

## Report
`list_speakers` fails the whole call when a single speaker's per-speaker UPnP
reads raise, even though discovery itself succeeded. The reads are volume,
mute and group coordinator, done in `_speaker_dict`.

Observed on 2026-09-28 during Mission 04 Flight 01, right after a full-speed
subnet scan:

> `Error calling tool 'list_speakers': HTTPConnectionPool(host='192.168.86.51', port=1400) ... [Errno 101] Network is unreachable`

To reproduce, stub one speaker's `volume` to raise. `list_speakers` then
raises instead of returning the other four.

## Evidence
- `mcp_sonos/controller.py:_speaker_dict` reads `speaker.volume`,
  `speaker.mute` and `_coordinator_of(speaker)` with no guard.
- `SonosController.list_speakers` returns
  `[_speaker_dict(s) for s in self._speakers_fresh()]`, so one exception
  aborts the list.
- Source: [M04 F01 debrief](../missions/04-discovery-and-targeting/flights/01-zero-config-discovery/flight-debrief.md).

## Corrective Action
*(written at completion)*

## Verification

## Sign-Off
*(written at completion)*

## Disposition
