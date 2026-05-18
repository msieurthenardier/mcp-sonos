# Flight: Test Scaffolding

**Status**: ready
**Mission**: [Baseline Maintenance](../../mission.md)

## Contributing to Criteria

**Mission success criterion (the only remaining one — final flight):**
- [ ] F7 — Pytest scaffolding exists; `SonosController` construction is deferred from module-level; a `SoCoFake` lets controller and playlists logic be exercised without live hardware; at least the F1 takeover path has a regression test

**Carry-forwards from Flight 02 + Flight 03 debriefs (bundled here — testing-themed and share Flight 04's surface):**
- [ ] Smoke scripts honor `SONOS_IPS=` for deterministic startup (Flight 02 debrief — closes the SSDP-discovery race failure mode that smoke tests currently exhibit intermittently)
- [ ] `controller.py:86` class docstring drift fix (`"speakers cache + audio host + lock"` → drop `+ lock`, since Flight 02 removed the lock) (Flight 02 debrief)
- [ ] First unit tests cover three pure-function targets from Flight 03 debrief: `validate_http_url`, `_verify_or_log`, F1 takeover path
- [ ] Investigate the `say()` coordinator bug as the first SoCoFake-driven test (mission Known Issues, reproducible 2/3 times in debrief smoke runs)

---

## Pre-Flight

### Objective
Honor the documented "controller is testable" claim AND close out the mission. Four legs: pre-flight cleanups (SSDP-deterministic smoke + docstring drift fix); test scaffolding (DI refactor + SoCoFake + pytest config); first unit tests covering three pure-function targets (`validate_http_url`, `_verify_or_log`, F1 takeover); and an investigation leg for the mission's only remaining real bug — the `say()` coordinator routing issue that has shown up in 2 of 3 prior debrief smoke runs.

### Open Questions
- [x] Where does controller construction live after defer? → Resolved: a `get_controller()` factory or a `register_tools(mcp, controller)` function. Picked `register_tools()` — keeps DI explicit. See Design Decisions.
- [x] What does `SoCoFake` need to support? → Resolved: a minimum surface matching the controller + playlists call sites. See Design Decisions.
- [x] Test runner config? → Resolved: pytest with `testpaths = ["tests"]`; `pytest` added to the SAME `[dev]` extras as `pip-audit` (per Flight 03 debrief recommendation — don't split into `[test]` extra).
- [x] What outcome shape for the `say()` bug investigation? → Resolved: instrument + reproduce the bug as a failing pytest test; fix if the root cause is small and obvious; otherwise mark `xfail` with a clear follow-up note. See Design Decisions.

### Design Decisions

**Factory pattern over lazy-init**: Use an explicit `register_tools(mcp, controller)` function called from `main()`. Don't do module-level lazy-init via a sentinel — too implicit.
- Rationale: makes the dependency obvious to readers; matches the "MCP-agnostic, unit-testable" architecture intent
- Trade-off: each tool function takes a controller reference via closure; small boilerplate

**Where SoCoFake lives**: `tests/_fakes.py` (private to tests, not exported as a project surface).
- Rationale: implementation detail of test scaffolding
- Trade-off: anyone wanting to embed mcp-sonos in their own test suite needs to copy the fake; acceptable for now

**SoCoFake minimal surface**: `player_name`, `uid`, `ip_address`, `is_visible()`, `group.coordinator` (returns self by default), `group.members` (returns `[self]` by default), `get_current_transport_info()` (state machine), `get_current_track_info()` (uri+title), `play_uri(uri, title=None, force_radio=False)`, `pause`, `stop`, `next`, `previous`, `volume` property (settable), `mute`/`unmute`, `unjoin`, `join(coord)`, `add_to_queue`, `clear_queue`. Transport state transitions are explicit (test code drives `_transport["current_transport_state"]` directly).
- Rationale: cover exactly what `controller.py` and `playlists.py` actually call. No speculative surface.
- Trade-off: any new SoCo surface added later needs SoCoFake updates; acceptable

**pytest in `[dev]` (not a separate `[test]` extra)**: Per Flight 03 debrief recommendation — pip-audit and pytest are both maintainer-only.
- Rationale: simple `pip install -e ".[dev]"` flow
- Trade-off: forces a `dev` install for testing; not actually a trade-off in practice

**`say()` bug investigation scope** (Leg 04): write a failing pytest test that reproduces the `play_uri can only be called/used on the coordinator in a group` error against `SoCoFake`. If the root cause turns out to be small (e.g. `_resolve_coordinator` returns a non-coordinator in a specific state and the fix is 5 lines), implement the fix in the same leg. If the investigation reveals deeper SoCo-vs-firmware divergence that requires significant refactor, leave the test as `xfail` with a clear follow-up note and the mission Known Issue stays open.
- Rationale: bounds investigation scope so Leg 04 can't become a rabbit hole
- Trade-off: mission may close with the bug still unfixed; acceptable — F7's success criterion is "regression test scaffolding exists," not "the say() bug is fixed"

**Smoke-script SSDP determinism (Leg 01)**: Set `SONOS_IPS=<comma-separated>` as a sensible default at the top of both `smoke_test.py` and `playlist_smoke.py` — pulled from a small constant or env-var with a docstring explaining the substitution. Don't change runtime defaults in the project — only the smoke scripts.
- Rationale: deterministic startup for the maintainer's environment without breaking other users
- Trade-off: the maintainer's specific speaker IPs leak into the smoke scripts — but the LAN IPs were just anonymized in Flight 02 Leg 03, so use the `192.168.1.x` placeholders consistent with `.env.example`. Operator overrides via env var if they're on a different LAN.

### Prerequisites
- [x] Flight 1 has landed (F1 fix is in place — verified post-Flight-01 commits)
- [x] Flight 3's `[dev]` optional-deps block exists in `pyproject.toml` (pytest can be added alongside `pip-audit`)
- [ ] Pre-flight smoke baseline against live hardware — `playlist_smoke.py` should pass; `smoke_test.py` may continue to fail with the `say()` coordinator bug (which Leg 04 is investigating)

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [ ] Pre-flight smoke baseline recorded in flight log
- [x] Validation approach defined
- [x] Legs defined
- [x] Design reviewed by Architect (notes in flight log)

---

## In-Flight

### Technical Approach
Four legs. Leg 01 is small (smoke + docstring cleanups). Leg 02 is the largest (DI refactor + SoCoFake + pytest scaffolding — the architectural backbone). Leg 03 is content (unit tests using the scaffolding). Leg 04 is investigative (reproduce + maybe fix the `say()` bug).

**Commit cadence**: per-leg commits (Flights 01, 02, 03 convention preserved).

**Agent pattern** (per Flight 02 + 03 rule of thumb):
- Leg 01: consolidated review+implement (text/config cleanups, runtime-inert)
- Leg 02: split design-review + implementation (DI refactor has runtime semantics — module import side effects, FastMCP integration; warrants the layered review)
- Leg 03: split design-review + implementation (unit tests have semantic content worth reviewing — assertion shape, fake usage, regression-pin correctness)
- Leg 04: split design-review + implementation (investigative; the test shape and fix-or-xfail decision both benefit from review)

**Smoke-test relevance**:
- Leg 01 changes smoke scripts directly — re-run after the change to confirm `SONOS_IPS=` determinism works
- Leg 02 changes `server.py` import semantics — `python -c "import mcp_sonos.server"` must no longer bind a TCP port
- Leg 03 adds pytest tests — `pytest` must pass with no live Sonos; smoke tests still pass against live hardware (no behavior change)
- Leg 04 may change `controller.py` `say()` or `_resolve_coordinator` — smoke `say()` path must work after the leg lands (or `xfail` clearly documents why not)

### Checkpoints
- [ ] Leg 01: `SONOS_IPS=` default present in both smoke scripts; `controller.py:86` docstring no longer mentions `+ lock`
- [ ] Leg 02: `python -c "import mcp_sonos.server"` does NOT bind a TCP port; `tests/_fakes.py::SoCoFake` exists; `pytest` in `[dev]` extras; `pytest` runs (even if 0 tests collected)
- [ ] Leg 03: at least 3 unit tests pass (`validate_http_url`, `_verify_or_log` happy + tamper, F1 takeover regression); `pytest` exits 0 with no live hardware reachable
- [ ] Leg 04: `say()` bug reproduced as a failing or `xfail`-marked test; if fixed in this leg, smoke `say` passes; if `xfail`, follow-up captured in mission Known Issues update

### Adaptation Criteria

**Divert if**:
- The DI refactor reveals that `register_tools(mcp, controller)` doesn't cleanly fit FastMCP's tool registration API — fall back to a controller-singleton-at-`main`-time pattern with a brief justification in the flight log
- The `say()` bug investigation reveals a SoCo-vs-firmware divergence that requires changes to a significant fraction of `controller.py` — STOP the leg, mark the test `xfail`, document the investigation findings in the mission Known Issues update, defer the actual fix to a future maintenance flight. Don't let Leg 04 spiral.
- `playlist_smoke.py` starts failing in a NEW way distinct from the two known modes (`say()` coordinator bug + SSDP race) — halt and investigate

**Acceptable variations**:
- SoCoFake interface drift during writing — minimize but don't over-engineer
- Unit test count growing past 3 in Leg 03 — fine, more coverage is good
- If Leg 03's tests reveal additional bugs in `_urls.py` or `_verify_or_log`, fix them in Leg 03; if they reveal bugs requiring controller-level changes, defer

### Legs

- [ ] `01-flight-prereqs` — SSDP-deterministic smoke scripts + `controller.py:86` class docstring drift fix (bundled cleanups; Flight 02 debrief carry-forwards)
- [ ] `02-test-scaffolding-and-di-refactor` — DI refactor (defer module-level `SonosController()` in `server.py`; `register_tools(mcp, controller)` factory) + `SoCoFake` in `tests/_fakes.py` + pytest config in `pyproject.toml` + `pytest` in `[dev]` extras (F7 core architectural backbone)
- [ ] `03-first-unit-tests` — Three pure-function tests using the scaffolding: `tests/test_urls.py` (validate_http_url happy + bad scheme + no netloc), `tests/test_tts_verify.py` (`_verify_or_log` happy + tamper + no-pin warning + `_hash_voice_file`), `tests/test_playlists_takeover.py` (F1 takeover regression via SoCoFake)
- [ ] `04-investigate-say-coordinator-bug` — Reproduce mission Known Issue as a SoCoFake-driven test; instrument `controller.py:_resolve_coordinator` if needed; fix-or-xfail decision per scope

---

## Post-Flight

### Completion Checklist
- [ ] All 4 legs completed (each with its own commit)
- [ ] `pytest` runs from the venv with no live hardware connected; ≥3 tests pass
- [ ] Smoke tests still pass against live hardware (`playlist_smoke.py` at minimum; `smoke_test.py` if Leg 04 fixed `say()`)
- [ ] Maintenance report finding F7 ticked in mission.md
- [ ] All 4 mission flights ticked in mission.md
- [ ] Mission Known Issues updated: `say()` bug either resolved (Leg 04 fix) or expanded with investigation findings (Leg 04 `xfail`)
- [ ] Flight log filled in (per-leg entries + final summary + test-metrics baseline)
- [ ] CLAUDE.md updated: mention `pytest` as a regression net (no longer "smoke tests only")
- [ ] PR opened (Flight Director step)

### Verification
- `python -c "import mcp_sonos.server"` — no `OSError: Address already in use`, no audio host thread bound
- `cd /home/cprch/projects/mcp-sonos && .venv/bin/pytest` — exits 0 with no live hardware reachable; ≥3 tests pass; 0 or 1 `xfail` (the `say()` bug if not fixed in Leg 04)
- `python smoke_test.py` — passes if Leg 04 fixed `say()`; expected `say()` failure if `xfail`-ed
- `python playlist_smoke.py` — still passes
- `git grep "+ lock" mcp_sonos/` — zero hits in the class docstring
- `grep -n "SONOS_IPS" smoke_test.py playlist_smoke.py` — both scripts set/honor it
