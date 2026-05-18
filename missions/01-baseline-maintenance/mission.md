# Mission: Baseline Maintenance

**Status**: planning

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

- [ ] F1 — `playlists.py:380` no longer references a nonexistent attribute; external-takeover detection logs cleanly
- [ ] F2 — `play_file` rejects paths outside `AUDIO_MEDIA_ROOT` (configurable env var) with a clear error; audio host directory listing is disabled
- [ ] F3 — `AUDIO_PORT` outside 8000–8999 raises a clear `ValueError` at startup, referencing the firewall rule
- [ ] F4 — `say` tool docstring describes Piper accurately (no gTTS/`lang` lie); `playlists.py:4` module docstring matches the CLAUDE.md speaker-UID keying invariant
- [ ] F5 — `say()` (and any other group-access site) routes through `_group_members_of`
- [ ] F6 — Unused `Iterable` import and dead `threading.Lock` removed from `controller.py`
- [ ] F7 — Pytest scaffolding exists; `SonosController` construction is deferred from module-level; a `SoCoFake` lets controller and playlists logic be exercised without live hardware; at least the F1 takeover path has a regression test
- [ ] F8 — Default Piper voice has a pinned SHA-256 verified on download; non-default voices logged as trust-on-first-use
- [ ] F10 — `poc/debug_play.py` and `CLAUDE.md` no longer contain the real LAN IPs; placeholders match `.env.example`'s `192.168.1.x` convention
- [ ] F11 — README "Architecture" section reflects 32 tools (or removes the count)
- [ ] F12 — `audio_host.url_for` URL-encodes filenames
- [ ] F13 — `pyproject.toml` caps `fastmcp` at `<4` (and other deps as appropriate)
- [ ] F14 — `play_url` and `playlist_add`/`playlist_add_many` reject non-`http`/`https` schemes with a clear error
- [ ] F17 — `pip-audit` baseline scan completed; results documented; pip-audit added to dev extras

## Stakeholders
Maintainer (msieurthenardier). Self-deployed on home LAN; no external users.

## Constraints
- All reviewers ran read-only and flagged only items that match real risk for a single-developer hobbyist project on a trusted home LAN. Don't expand scope beyond the listed findings during execution.
- Each flight should commit at landing; don't conflate flights.
- Smoke tests still require live Sonos hardware. Unit-test scaffolding (F7) is the first attempt at hardware-free regression coverage; expect some iteration on the SoCo fake's shape.

## Environment Requirements
- Existing local Python venv at `/home/cprch/projects/mcp-sonos/.venv`
- Live Sonos hardware on LAN for smoke-test verification (`smoke_test.py`, `playlist_smoke.py`)
- No CI to satisfy

## Open Questions
N/A — findings are well-scoped from inspection; execution decisions belong in individual flight Open Questions.

## Known Issues

- [ ] Audio host LAN bind (F9) and TTS cache growth (F21) remain Pass (known-debt) — documented and accepted within trusted-LAN threat model. Out of scope for this mission. Revisit if deployment posture changes.

## Flights

> **Note:** These four flights cover the full scoped finding set. Order is recommended (Flight 1 first — highest value, blocks nothing else; Flight 4 last — biggest, no urgency). Each can land independently.

- [ ] Flight 1: [Correctness and Capability Hardening](flights/01-correctness-and-capability/flight.md) — F1, F2, F3, F5, F12, F14
- [ ] Flight 2: [Documentation Cleanup](flights/02-documentation-cleanup/flight.md) — F4, F6, F10, F11
- [ ] Flight 3: [Supply-Chain Hardening](flights/03-supply-chain-hardening/flight.md) — F8, F13, F17
- [ ] Flight 4: [Test Scaffolding](flights/04-test-scaffolding/flight.md) — F7
