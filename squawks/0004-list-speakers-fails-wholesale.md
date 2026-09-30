# Squawk 0004: `list_speakers` fails wholesale on one speaker's transient UPnP error

**Status**: completed
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: 2026-09-30

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
`mcp_sonos/controller.py:_speaker_dict` now wraps its UPnP reads
(`player_name`, `_coordinator_of`, `volume`, `mute`) in a `try`/`except
Exception`. On failure it returns a degraded entry — `name` (best-effort:
tried again, falls back to `ip` if even that raises), `ip` (a plain
attribute set at `SoCo.__init__`, never a network call, so always safe),
and `error: str(e)` — instead of raising. `speaker.ip_address` needs no
guard since it's never fetched over the network.

Both `SonosController.list_speakers` and `SonosController.refresh` already
route every speaker through this same `_speaker_dict` call in their list
comprehensions, so both get the guard for free — no separate change
needed in either method.

`mcp_sonos/server.py`'s `list_speakers` tool docstring now documents that
a speaker can come back degraded with only `name`, `ip`, and `error`
(docstring only, no logic change in `server.py`).

## Verification
- Added `tests/test_discovery.py::test_list_speakers_degrades_single_unreachable_speaker`:
  two fake speakers, one (`Patio`) with its `volume` property raising
  `ConnectionError("[Errno 101] Network is unreachable")` (mirrors the
  reported error). Asserts `list_speakers()` still returns both entries —
  `Kitchen` full and unaffected, `Patio` degraded to `name`/`ip`/`error`
  with no `volume` key.
- `timeout 180 .venv/bin/python -m pytest -q`: **174 passed** before this
  change, **175 passed** after (net +1 test), no regressions.

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review. There were two cycles. Cycle 1 confirmed all four fixes. The Flight Director then required a fix for the suite runtime regression: the 0007 tests slept for real, taking the suite from 2.9 s to 11.8 s. A fake clock was added, and cycle 2 confirmed it (177 passed, 3.7 s).
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-30` on `squawk/turnaround-2026-09-30`

## Disposition
