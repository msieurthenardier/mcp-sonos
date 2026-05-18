# Mission: Baseline Maintenance

**Status**: active

## Outcome
Resolve the 14 codebase health items identified in the 2026-05-18 maintenance report. After this mission, mcp-sonos should be free of the real correctness bug, have a properly scoped `play_file` capability, validate `AUDIO_PORT` against the documented firewall range, have its documentation aligned with actual behavior, carry pinned supply-chain hashes, and ship with unit-test scaffolding so the documented "controller is testable" claim is real.

## Context
First post-init maintenance cycle for mcp-sonos. The project is small (~9 source files), well-maintained, and explicitly documents a trusted-LAN threat model. Inspection findings sit on three axes:
- **One real bug** (playlists.py:380 AttributeError on every external takeover)
- **One threat-model-crossing capability** (play_file with no allow-list)
- **A cluster of doc/config/hardening items** that compound if left

User reinstated five originally-deferred items (F7, F8, F13, F14, F17) into mission scope — broader than the Architect's recommended shortlist, but coherent as a baseline-quality bar before the next feature mission.

Full inspection details: [Maintenance Report 2026-05-18](../../maintenance/2026-05-18.md).

## Success Criteria

- [x] F1 — `playlists.py:380` no longer references a nonexistent attribute; external-takeover detection logs cleanly
- [x] F2 — `play_file` rejects paths outside `AUDIO_MEDIA_ROOT` (configurable env var) with a clear error; audio host directory listing is disabled
- [x] F3 — `AUDIO_PORT` outside 8000–8999 raises a clear `ValueError` at startup, referencing the firewall rule
- [x] F4 — `say` tool docstring describes Piper accurately (no gTTS/`lang` lie); `playlists.py:4` module docstring matches the CLAUDE.md speaker-UID keying invariant
- [x] F5 — `say()` (and any other group-access site) routes through `_group_members_of`
- [x] F6 — Unused `Iterable` import and dead `threading.Lock` removed from `controller.py`
- [ ] F7 — Pytest scaffolding exists; `SonosController` construction is deferred from module-level; a `SoCoFake` lets controller and playlists logic be exercised without live hardware; at least the F1 takeover path has a regression test
- [x] F8 — Default Piper voice has a pinned SHA-256 verified on download; non-default voices logged as trust-on-first-use
- [x] F10 — `poc/debug_play.py` and `CLAUDE.md` no longer contain the real LAN IPs; placeholders match `.env.example`'s `192.168.1.x` convention
- [x] F11 — README "Architecture" section reflects 32 tools (or removes the count)
- [x] F12 — `audio_host.url_for` URL-encodes filenames
- [x] F13 — `pyproject.toml` caps `fastmcp` at `<4` (and other deps as appropriate)
- [x] F14 — `play_url` and `playlist_add`/`playlist_add_many` reject non-`http`/`https` schemes with a clear error
- [x] F17 — `pip-audit` baseline scan completed; results documented; pip-audit added to dev extras

## Stakeholders
Maintainer (msieurthenardier). Self-deployed on home LAN; no external users.

## Constraints
- All reviewers ran read-only and flagged only items that match real risk for a single-developer hobbyist project on a trusted home LAN. Don't expand scope beyond the listed findings during execution.
- Each flight should commit at landing; don't conflate flights.
- Smoke tests still require live Sonos hardware. Unit-test scaffolding (F7) is the first attempt at hardware-free regression coverage; expect some iteration on the SoCo fake's shape.

## Environment Requirements
- Existing local Python venv at `<repo-root>/.venv`
- Live Sonos hardware on LAN for smoke-test verification (`smoke_test.py`, `playlist_smoke.py`)
- No CI to satisfy

## Open Questions
N/A — findings are well-scoped from inspection; execution decisions belong in individual flight Open Questions.

## Known Issues

- [ ] Audio host LAN bind (F9) and TTS cache growth (F21) remain Pass (known-debt) — documented and accepted within trusted-LAN threat model. Out of scope for this mission. Revisit if deployment posture changes.
- [x] **`say()` coordinator-routing bug** — surfaced during Flight 01 execution and confirmed pre-existing during the Flight 01 debrief. `smoke_test.py` failed with `play_uri can only be called/used on the coordinator in a group` at `controller.py:328`, even when `list_groups` showed the target speaker as its own singleton coordinator. **Resolved in Flight 04 Leg 04** (`controller.py::_play_uri_with_stale_coord_retry`). Investigation finding: `coord.uid` and `coord.group.coordinator.uid` agree at the call site — the divergence is between SoCo's in-process cache and the Sonos firmware, invisible to controller-level inspection. Fix: catch `SoCoSlaveException` from `coord.play_uri` in `say()`, invalidate the speakers cache (`_speakers_ts = 0.0`), re-resolve the coordinator via fresh SSDP/SONOS_IPS discovery, retry once. Pinned by two `SoCoFake`-driven tests in `tests/test_say_coordinator.py` (recovery happy path + worst-case bound-after-single-retry). **Live-hardware smoke verification deferred** — `smoke_test.py` itself is currently broken by an unrelated Leg 02 DI-refactor regression (the in-process Client imports `mcp` directly but tools are now registered inside `main()`); flagged as a new Known Issue below.

- [x] **Smoke scripts no longer functional after Leg 02 DI refactor** — surfaced during Flight 04 Leg 04 attempt at hardware verification of the `say()` fix. Two regressions, both in the smoke scripts (not in `mcp_sonos/`):
  1. `smoke_test.py:22` imports `mcp` from `mcp_sonos.server` and runs `Client(mcp)` against it without ever calling `main()`. After Leg 02 moved tool registration from module top-level into `register_tools(mcp, controller)` called from `main()`, the imported `mcp` instance has zero tools. Run output: `Server exposes 0 tools:` followed by `fastmcp.exceptions.ToolError: Unknown tool: 'list_speakers'`.
  2. `playlist_smoke.py:35` imports `mcp, controller` from `mcp_sonos.server`. After Leg 02 removed the module-level `controller = SonosController()`, this import will raise `ImportError`.

  **Fix shape**: both scripts should construct a `SonosController` and call `register_tools(mcp, controller)` before opening the `Client(mcp)`. Out of scope for Flight 04 Leg 04 (surface guard limits the leg to `controller.py` coordinator-resolution code). **Resolved in Flight 04 Leg 05** — added `from mcp_sonos.controller import SonosController`, switched `from mcp_sonos.server import mcp, controller` → `from mcp_sonos.server import mcp, register_tools`, and constructed a local `controller` + called `register_tools(mcp, controller)` before any `Client(mcp)` usage in both scripts (function-local in `smoke_test.py::main()`; module-level in `playlist_smoke.py` because `build_playlist()` closes over `controller`). The pytest suite (`tests/`) was unaffected — only the live-hardware smoke harness. **Live-hardware re-run deferred** — Sonos LAN unreachable from the Leg 05 session; static `py_compile` + import-shape checks pass. First end-to-end green `smoke_test.py` (including `say()` thanks to Leg 04's fix) remains a post-handoff verification step.

## Flights

> **Note:** These four flights cover the full scoped finding set. Order is recommended (Flight 1 first — highest value, blocks nothing else; Flight 4 last — biggest, no urgency). Each can land independently.

- [x] Flight 1: [Correctness and Capability Hardening](flights/01-correctness-and-capability/flight.md) — F1, F2, F3, F5, F12, F14
- [x] Flight 2: [Documentation Cleanup](flights/02-documentation-cleanup/flight.md) — F4, F6, F10, F11 (plus 3 debrief follow-ups bundled into the flight)
- [x] Flight 3: [Supply-Chain Hardening](flights/03-supply-chain-hardening/flight.md) — F8, F13, F17
- [ ] Flight 4: [Test Scaffolding](flights/04-test-scaffolding/flight.md) — F7
