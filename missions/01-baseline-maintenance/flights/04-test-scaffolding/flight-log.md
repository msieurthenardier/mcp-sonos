# Flight Log: Test Scaffolding

**Flight**: [Test Scaffolding](flight.md)

## Summary
(Filled in during execution.)

---

## Reconnaissance Report

Verified each scope item against current code at flight planning time (2026-05-18, after Flights 01-03 landed; current HEAD on `flight/03-supply-chain-hardening` at `989c171`). Source artifacts: [`maintenance/2026-05-18.md`](../../../../maintenance/2026-05-18.md) for F7, plus carry-forward Action Items from Flight 02 and Flight 03 debriefs.

| Item | Classification | Evidence | Recommendation |
|------|----------------|----------|----------------|
| F7 — Module-level `controller = SonosController()` in `server.py` | `confirmed-live` | `mcp_sonos/server.py:34` — `controller = SonosController()` at module top-level (line 33 has it commented above). Importing the module starts the audio host. | Defer via `register_tools(mcp, controller)` called from `main()`. |
| F7 — `tests/` directory + pytest config | `confirmed-live` | No `tests/` directory exists. `pyproject.toml` has no `[tool.pytest.ini_options]` block. `[dev]` optional-deps contains only `pip-audit`. | Create `tests/__init__.py`, `tests/_fakes.py::SoCoFake`, add pytest config + pytest to `[dev]`. |
| F7 — SoCoFake | `confirmed-live` | No fake exists. Reference for needed surface: `mcp_sonos/controller.py` and `mcp_sonos/playlists.py` SoCo call sites. | Per flight design — minimal surface in `tests/_fakes.py`. |
| Flight 02 debrief AI — SSDP-deterministic smoke scripts | `confirmed-live` | `grep -n "SONOS_IPS" smoke_test.py playlist_smoke.py` returns zero hits. Both scripts rely on SSDP discovery, which can race. | Set `os.environ.setdefault("SONOS_IPS", "192.168.1.51,...")` at the top of both scripts. |
| Flight 02 debrief AI — `controller.py:86` class docstring drift | `confirmed-live` | `mcp_sonos/controller.py:85` reads `"""Stateful controller: speakers cache + audio host + lock."""`. The `self._lock` it referred to was removed in Flight 02 Leg 02. | Drop `+ lock` from the docstring. |
| Flight 03 debrief AI — first unit-test targets (validate_http_url, _verify_or_log, F1 takeover) | `confirmed-live` (target code exists, no tests) | `mcp_sonos/_urls.py::validate_http_url` exists; `mcp_sonos/tts.py::_verify_or_log` + `_hash_voice_file` exist; `mcp_sonos/playlists.py:380` F1 takeover branch correctly references `session.speaker_name` (Flight 01 fix). All three are ideal pure-function unit-test targets. No tests exist yet. | Three test modules in Leg 03 covering these targets. |
| Flight 03 debrief AI — say() coordinator bug investigation | `confirmed-live` (open Known Issue) | Mission Known Issues entry: `say()` fails with `play_uri can only be called/used on the coordinator in a group` even when target speaker is its own singleton coordinator. Reproduced in 2 of 3 prior debrief smoke runs. Pre-debrief "Sonos topology" hypothesis was refuted in Flight 03 debrief. | Reproduce as SoCoFake-driven failing pytest test in Leg 04; fix-or-xfail per scope guard. |

**No items retired or scoped down — all 7 confirmed-live.** This is the largest scope reconciliation of any flight in this mission: 1 mission criterion (F7) + 2 Flight 02 debrief AIs + 4 Flight 03 debrief AIs.

### Additional Observations

1. **Flight 04 is the final flight of the mission.** Successful execution lands F7 (the last open mission criterion); closes either as resolution or `xfail` the `say()` coordinator bug; and consolidates 3 carry-forward Action Items that have been open across multiple debriefs.

2. **Leg 04 is the only investigative leg in the mission.** All prior legs were "implement per spec." Leg 04 has explicit fix-or-xfail decision tree with a scope-guard (>30 lines → xfail). Good methodology test for how `/agentic-workflow` handles open-ended investigation.

3. **`_verified_voices` thread-safety invariant** (from Flight 03 debrief) is NOT addressed in this flight — it requires the test scaffolding from Leg 02 to be exercised before any structural change to `_VoiceCache`. Carry-forward for a future micro-flight.

4. **Methodology heuristics** identified by Flight 03 debrief ("hardware-free verifiability" + "split-vs-consolidate" as `/flight` skill design heuristics) are mission-control improvements, not mcp-sonos changes. Out of scope for Flight 04.

5. **CLAUDE.md update** to mention `pytest` as a regression net (no longer "smoke tests only" per the existing claim at line 34) is in Leg 02's Outputs but worth flagging here: it's a documentation surface change in the flight, not just a code change.

---

---

## Leg Progress

(Append entries here as legs land.)

---

## Decisions

---

## Deviations

---

## Anomalies

---

## Session Notes
