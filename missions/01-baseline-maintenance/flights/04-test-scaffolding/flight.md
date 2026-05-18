# Flight: Test Scaffolding

**Status**: ready
**Mission**: [Baseline Maintenance](../../mission.md)

## Contributing to Criteria
- [ ] F7 — Pytest scaffolding exists; `SonosController` construction is deferred from module-level; a `SoCoFake` lets controller and playlists logic be exercised without live hardware; at least the F1 takeover path has a regression test

---

## Pre-Flight

### Objective
Honor the documented "controller is testable" claim. Three concerns merged into one flight: (a) defer module-level `SonosController()` construction in `server.py:33` so imports don't bind a TCP port; (b) introduce a `SoCoFake` adequate for exercising controller transport methods and the playlists worker's takeover/skip/back/stop signals; (c) add pytest scaffolding (config in pyproject.toml, `tests/` directory, dev extras) and write at least one regression test pinning the F1 fix (`playlists.py:380` takeover-detection no longer raises `AttributeError`).

### Open Questions
- [x] Where does controller construction live after defer? → Resolved: a `get_controller()` factory in `controller.py` (cached singleton), invoked from `main()` in `server.py`. Tools take `controller = get_controller()` at the top of each tool function — or, better, are constructed inside a `register_tools(mcp, controller)` function called from `main()`. Pick the second; it keeps the controller-as-DI explicit.
- [x] What does `SoCoFake` need to support? → Resolved: `player_name`, `uid`, `ip_address`, `group.coordinator` (returns self by default), `group.members` (returns `[self]` by default), `is_visible` (True), `get_current_transport_info()`, `get_current_track_info()`, `play_uri(uri, title=None, force_radio=False)`, `pause`, `stop`, `next`, `previous`, `set_volume`, `mute`/`unmute`, `unjoin`, `add_to_queue`/`remove_from_queue`/`clear_queue`, `join(coord)`. Tracking state for transport info is the bulk of the work; transitions follow play→playing→stopped via explicit driver hooks the test uses.
- [x] Test runner config? → Resolved: pytest with `testpaths = ["tests"]` and `[tool.pytest.ini_options]` in pyproject.toml. No fixtures lib beyond stdlib `unittest.mock`.

### Design Decisions

**Factory pattern over lazy-init**: Use an explicit `get_controller()` factory and a `register_tools(mcp, controller)` function. Don't do module-level lazy-init via a sentinel — too implicit.
- Rationale: makes the dependency obvious to readers; matches the "MCP-agnostic, unit-testable" architecture intent
- Trade-off: each tool function takes a controller reference via closure; small boilerplate

**Where SoCoFake lives**: `tests/_fakes.py` (private to tests, not exported as a project surface).
- Rationale: implementation detail of test scaffolding
- Trade-off: anyone wanting to embed mcp-sonos in their own test suite needs to copy the fake; acceptable for now

**First regression test target**: F1 — call the playlists worker tick directly with state simulating an external takeover, assert no AttributeError and that the warning log mentions the speaker name.
- Rationale: pin the bug we're fixing in Flight 1; smallest end-to-end path through the worker
- Trade-off: only one test in the initial scaffolding — coverage grows over time

### Prerequisites
- [ ] Flight 1 has landed (specifically F1 fix is in place)

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [ ] Prerequisites verified (Flight 1 landed)
- [x] Validation approach defined (test must pass; smoke tests still pass)
- [x] Legs defined

---

## In-Flight

### Technical Approach
Single leg covering DI refactor + fake + pytest config + first regression test. Conceptually one change ("the project can be unit-tested"), even though it touches multiple files. If at any point the scope explodes (e.g., the SoCoFake needs to model much more SoCo surface than the takeover branch needs), split into a follow-up leg.

### Checkpoints
- [ ] DI refactor lands: `python -c "import mcp_sonos"` no longer binds a TCP port
- [ ] `SoCoFake` exists in `tests/_fakes.py`
- [ ] `pytest` config in `pyproject.toml`; `pip install -e ".[dev]"` installs pytest
- [ ] First test passes: `tests/test_playlists.py::test_takeover_logs_cleanly`
- [ ] Smoke tests still pass against live hardware

### Adaptation Criteria

**Divert if**:
- The DI refactor reveals that `register_tools(mcp, controller)` doesn't cleanly fit FastMCP's tool registration API — fall back to a controller-singleton-at-`main`-time pattern.

**Acceptable variations**:
- Test framework choice (pytest is the assumption; if `unittest`-only feels lighter for first leg, OK).
- SoCoFake interface drift during writing — minimize but don't over-engineer.

### Legs

- [ ] `01-add-pytest-scaffolding-and-soco-fake` — F7: DI refactor + fake + pytest + first regression test

---

## Post-Flight

### Completion Checklist
- [ ] Leg completed
- [ ] Smoke tests still pass against live hardware
- [ ] `pytest` runs from the venv with no live hardware connected
- [ ] Maintenance report finding F7 ticked in mission.md
- [ ] Flight log filled in
- [ ] Update CLAUDE.md to mention `pytest` as a regression-net option (no longer "smoke tests only")

### Verification
- `python -c "import mcp_sonos; import mcp_sonos.server"` — no `OSError: Address already in use`, no audio host bound.
- `cd /home/cprch/projects/mcp-sonos && .venv/bin/pytest` — 1 test passes, exits 0, on a machine with no Sonos hardware reachable.
- `python smoke_test.py` still works against live hardware.
