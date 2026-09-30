# Squawk 0005: CLAUDE.md doesn't name the learned-seed module state or its single-request assumption

**Status**: completed
**Type**: servicing
**Severity**: routine
**Reported**: 2026-09-29
**Completed**: 2026-09-30

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
Updated CLAUDE.md's Architecture section, right after the `SonosController`
"Owns:" list, with a new paragraph: the controller isn't the only
state-ownership pattern in the codebase — `mcp_sonos/speakers.py`'s
module-level `_learned_seed_ips` is a deliberate second one. Named it as the
IPs from the last successful `discover_speakers()` call, replaced wholesale
on each success and left untouched on `NoSpeakersFound`, with test-only reset
via `_reset_learned_seeds()`. Stated its safety invariant explicitly: only
one discovery runs at a time, which holds today because stdio transport plus
synchronous tool handling serialize every MCP call, and that a transport or
concurrency change must revisit it (add a lock, or move the state into the
controller). Verified the description against the actual
`mcp_sonos/speakers.py` source (`_learned_seed_ips`, `_record_learned_seeds`,
`_reset_learned_seeds`, `_learned_seed_stage`) before writing — no code
changed, doc-only.

## Verification
`timeout 180 .venv/bin/python -m pytest -q` → 175 passed, unchanged from
before the edit (doc-only change, no source touched).

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review. There were two cycles. Cycle 1 confirmed all four fixes. The Flight Director then required a fix for the suite runtime regression: the 0007 tests slept for real, taking the suite from 2.9 s to 11.8 s. A fake clock was added, and cycle 2 confirmed it (177 passed, 3.7 s).
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-30` on `squawk/turnaround-2026-09-30`

## Disposition
