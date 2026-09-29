# Squawk 0005: CLAUDE.md doesn't name the learned-seed module state or its single-request assumption

**Status**: open
**Type**: servicing
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: —

## Report
Mission 04 Flight 01 added process-wide, module-level state to
`mcp_sonos/speakers.py`: `_learned_seed_ips`, which holds the IPs from the
last successful discovery. It is the first mutable cache not owned by
`SonosController`.

Its safety rests on one assumption: only one discovery runs at a time, which
holds under stdio transport and synchronous tool handling. That assumption
lives only in a code comment. CLAUDE.md's Architecture section still says the
controller owns all caches.

Name the learned-seed state as a deliberate second state-ownership pattern and
state the single-request invariant, so that a future transport or concurrency
change doesn't break it silently.

## Evidence
- `mcp_sonos/speakers.py`: module-level `_learned_seed_ips`,
  `_record_learned_seeds()` and `_reset_learned_seeds()`
- CLAUDE.md "Architecture" says `SonosController` "Owns: Cached speaker list…"
  and makes no mention of the learned seeds.
- Source: [M04 F01 debrief](../missions/04-discovery-and-targeting/flights/01-zero-config-discovery/flight-debrief.md),
  from the Architect and Developer debrief interviews.

## Corrective Action
*(written at completion)*

## Verification

## Sign-Off
*(written at completion)*

## Disposition
