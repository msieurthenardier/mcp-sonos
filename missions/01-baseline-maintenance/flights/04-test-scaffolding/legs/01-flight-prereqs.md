# Leg: 01-flight-prereqs

**Status**: completed
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Land two bundled small cleanups from prior debriefs before the main scaffolding work begins: (a) set `SONOS_IPS=` as a deterministic-startup default in the smoke scripts so the SSDP-discovery race failure mode (Flight 02 debrief) stops being intermittent; (b) fix the `controller.py:86` class docstring drift (`"speakers cache + audio host + lock"` — the lock was removed in Flight 02 Leg 02).

## Context
- **Flight 02 debrief** identified two distinct `smoke_test.py` failure modes: the `say()` coordinator bug (dominant) AND an SSDP-discovery race (intermittent, fires when fewer than all speakers show up in the discovery window). The race was reproduced in the Flight 02 debrief: `smoke_test.py` reported `No speaker named 'Kitchen'. Available: 'Dining Room', 'Fireplace Room', 'Lounge', 'Patio'`. 30 seconds later `playlist_smoke.py` ran successfully against Kitchen. CLAUDE.md (lines 100-102) already documents `SONOS_IPS=ip1,ip2,...` as the deterministic-startup workaround; smoke scripts just don't use it.
- **Flight 02 debrief** also identified the `controller.py` class docstring (`SonosController`): still reads `"""Stateful controller: speakers cache + audio host + lock."""` even though Flight 02 Leg 02 deleted `self._lock`. Trivially fixable.
- Both items are independent of Flight 04's main scaffolding work and share theme (pre-flight cleanups + smoke determinism). Bundling avoids spawning two micro-flights.

## Inputs
- `smoke_test.py` and `playlist_smoke.py` (top-level smoke scripts; neither sets `SONOS_IPS`)
- `mcp_sonos/controller.py` around line 86 — the `SonosController` class docstring
- `.env.example` for the `SONOS_IPS` example format
- Flight 02 Leg 03 commit (`2162acc`) — established the `192.168.1.x` placeholder convention

## Outputs
- Both smoke scripts set or honor `SONOS_IPS=` with the project's documented placeholder IPs as a default
- `controller.py:86` class docstring no longer mentions `+ lock`
- No code-runtime behavior change for the controller itself; smoke scripts gain deterministic startup

## Acceptance Criteria
- [x] Both `smoke_test.py` and `playlist_smoke.py` set `os.environ.setdefault("SONOS_IPS", "...")` (or equivalent) at the top of the file. The default value uses the `192.168.1.x` placeholder family from `.env.example`. A user with different IPs can override via shell env var (`setdefault` honors existing env values)
- [x] Both smoke scripts include a comment near the `SONOS_IPS` setdefault explaining the SSDP-race rationale + how to override
- [x] `controller.py` `SonosController` class docstring no longer reads `"speakers cache + audio host + lock"` — replace with `"speakers cache + audio host"` (or rephrase to accurately reflect current state)
- [x] `git grep "+ lock" mcp_sonos/` returns no hits in the class docstring (only legitimate hits if any exist)
- [x] `git grep "speakers cache + audio host + lock"` returns zero hits anywhere — interpreted as scoped to live source files. Remaining hits are historical artifacts (Flight 02 debrief/log, Flight 04 recon table, this leg spec) that *quote* the old docstring as a reference; rewriting them would be revisionist. No live source-code hit.
- [x] Smoke tests still importable: `.venv/bin/python -m py_compile smoke_test.py playlist_smoke.py mcp_sonos/controller.py` clean

## Verification Steps
- `grep -n "SONOS_IPS" smoke_test.py playlist_smoke.py` — both should have at least one hit
- `grep -A 3 "class SonosController" mcp_sonos/controller.py` — docstring should not mention `lock`
- Optional (live hardware): re-run `smoke_test.py` and `playlist_smoke.py` after the change. The known `say()` coordinator bug may still fire in smoke_test.py (that's a separate fix, Leg 04). The SSDP race should NOT fire because IPs are now explicit.

## Implementation Guidance

1. **Smoke script update** (both files):
   - At the top of the file (after imports, before any other code), add:
     ```python
     import os
     # SSDP discovery can race when not all speakers are in the discovery window.
     # Set deterministic IPs by default; users with different LANs can override
     # by setting SONOS_IPS in the shell before running the script.
     # See CLAUDE.md "Operating constraints" for the SONOS_IPS convention.
     os.environ.setdefault("SONOS_IPS", "192.168.1.51,192.168.1.52,192.168.1.53,192.168.1.54,192.168.1.55")
     ```
   - The exact IP list should match the placeholder family in `.env.example` and CLAUDE.md (anonymized in Flight 02 to `192.168.1.x`). Pick 5 plausible addresses or whatever the placeholder docs use.

2. **Class docstring fix** (`mcp_sonos/controller.py` line ~86):
   - Current: `"""Stateful controller: speakers cache + audio host + lock."""`
   - Replacement: `"""Stateful controller: speakers cache + audio host."""` (drop `+ lock` — the actual lock now lives in `PlaylistManager`)
   - Alternative wording is fine — just don't mention `+ lock` as a controller attribute, since `controller.py` no longer has one.

3. **Verify**: `grep` per the AC list; `py_compile` on the three touched files.

## Files Affected
- `smoke_test.py` — top of file, ~6 lines added
- `playlist_smoke.py` — top of file, ~6 lines added (same block)
- `mcp_sonos/controller.py` — one-line class docstring change at line ~86

## Edge Cases
- **User has different LAN**: `os.environ.setdefault` only sets the default if the env var is unset. A user running the smoke script with `SONOS_IPS=10.0.0.5 python smoke_test.py` gets their value, not the placeholder. Acceptable — this matches the documented override convention.
- **CLAUDE.md class docstring reference**: CLAUDE.md mentions `SonosController` but doesn't quote its docstring. No CLAUDE.md change needed.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Update `../flight-log.md` with leg progress entry
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
