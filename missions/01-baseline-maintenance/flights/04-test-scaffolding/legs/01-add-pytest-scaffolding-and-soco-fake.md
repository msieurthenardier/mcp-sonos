# Leg: 01-add-pytest-scaffolding-and-soco-fake

**Status**: ready
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Make the documented "controller is testable" claim real: defer module-level `SonosController()` construction so imports don't bind a TCP port, introduce a `SoCoFake` adequate for exercising controller transport methods and the playlists worker, add pytest scaffolding (config + `tests/` directory + dev extras), and write a regression test pinning the F1 fix (Finding F7 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- CLAUDE.md:44 and README:370 both assert that `SonosController` is "MCP-agnostic, unit-testable." But: there is no `tests/` directory, no pytest in venv, no `pyproject.toml` test extras, no SoCo fake. The claim is aspirational.
- The module-level `controller = SonosController()` at `server.py:33` makes even importing the package start an AudioHost (TCP bind) and discover speakers. This blocks any test that wants to import `mcp_sonos.server` without live network.
- The threading invariants in `playlists.py` (worker keying, takeover detection, signal handling) are exactly the kind of logic that benefits most from unit tests.
- Architect's recommendation: use a `register_tools(mcp, controller)` factory pattern called from `main()`; put `SoCoFake` in `tests/_fakes.py`; pytest config in `pyproject.toml`; first regression test pins the F1 takeover-detection path.

## Inputs
- `mcp_sonos/server.py:33` module-level controller construction
- `mcp_sonos/controller.py` `SonosController` class
- `mcp_sonos/playlists.py` worker
- `pyproject.toml`
- No existing `tests/` directory

## Outputs
- `python -c "import mcp_sonos; import mcp_sonos.server"` does NOT bind a TCP port
- `tests/_fakes.py` with `SoCoFake` (and any other needed test doubles)
- `tests/test_playlists.py` with at least one test that exercises the takeover branch using the fake — pins F1's fix
- `pyproject.toml` `[tool.pytest.ini_options]` configured; `[project.optional-dependencies] dev` includes `pytest`
- `.venv/bin/pytest` passes without live hardware
- Smoke tests still pass against live hardware

## Acceptance Criteria
- [ ] `server.py` module-level `controller = SonosController()` removed; controller construction happens inside `main()` (or a `get_controller()` factory called from `main()`)
- [ ] `register_tools(mcp, controller)` (or equivalent pattern) wires tools to a controller instance passed in, not a global
- [ ] `tests/_fakes.py::SoCoFake` exists, implementing at minimum: `player_name`, `uid`, `ip_address`, `group.coordinator` (returns self by default), `group.members`, `is_visible`, `get_current_transport_info()`, `get_current_track_info()`, `play_uri`, `pause`, `stop`, `next`, `previous`, `set_volume`, `mute`/`unmute`, `unjoin`, `add_to_queue`, `clear_queue`, `join`
- [ ] `tests/test_playlists.py::test_takeover_logs_cleanly` (or similarly named) constructs a fake speaker, starts a playlist via `PlaylistManager`, simulates external takeover (different `current_track_info().uri`), asserts: no `AttributeError`, warning log contains the speaker name, worker stops cleanly
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`
- [ ] `pyproject.toml` `[project.optional-dependencies] dev` includes `pytest`
- [ ] `.venv/bin/pytest` runs and passes (1 test minimum)
- [ ] `smoke_test.py` and `playlist_smoke.py` still pass against live hardware

## Verification Steps
- `python -c "import mcp_sonos.server"` — no `OSError: Address already in use`, no AudioHost thread.
- `.venv/bin/pip install -e ".[dev]"` succeeds (after combining with the pip-audit dev extras from Flight 3).
- `.venv/bin/pytest -v` shows the test passing.
- `python smoke_test.py` and `python playlist_smoke.py` pass.

## Implementation Guidance

1. **Refactor `server.py`** to defer controller construction. Suggested shape:
   ```python
   # server.py
   from fastmcp import FastMCP
   from .controller import SonosController

   def create_app(controller: SonosController) -> FastMCP:
       mcp = FastMCP("sonos")
       register_tools(mcp, controller)
       return mcp

   def register_tools(mcp: FastMCP, controller: SonosController) -> None:
       @mcp.tool
       def list_speakers() -> ...:
           ...
       # ... all 32 tools defined here as closures over controller ...

   def main() -> None:
       controller = SonosController()
       app = create_app(controller)
       app.run()

   if __name__ == "__main__":
       main()
   ```

   This is the bulk of the refactor. The tool functions can be defined either as closures (cleanest for dependency injection) or as methods on a small `Tools` class — pick whichever reads better.

2. **Create `tests/_fakes.py`** with `SoCoFake`:
   ```python
   # tests/_fakes.py
   from dataclasses import dataclass, field
   from unittest.mock import MagicMock
   from typing import Optional

   @dataclass
   class FakeGroup:
       coordinator: "SoCoFake"
       members: list["SoCoFake"] = field(default_factory=list)

   @dataclass
   class SoCoFake:
       player_name: str = "Kitchen"
       uid: str = "RINCON_FAKE000000000"
       ip_address: str = "192.168.1.50"
       _transport: dict = field(default_factory=lambda: {"current_transport_state": "STOPPED"})
       _track: dict = field(default_factory=lambda: {"uri": "", "title": ""})

       def __post_init__(self):
           self.group = FakeGroup(coordinator=self, members=[self])

       def is_visible(self) -> bool:
           return True

       def get_current_transport_info(self) -> dict:
           return dict(self._transport)

       def get_current_track_info(self) -> dict:
           return dict(self._track)

       def play_uri(self, uri: str, title: Optional[str] = None, force_radio: bool = False) -> None:
           self._track = {"uri": uri, "title": title or ""}
           self._transport = {"current_transport_state": "PLAYING"}

       def pause(self) -> None:
           self._transport = {"current_transport_state": "PAUSED_PLAYBACK"}

       def stop(self) -> None:
           self._transport = {"current_transport_state": "STOPPED"}

       # ... add next, previous, set_volume, mute, unmute, unjoin, add_to_queue,
       #     clear_queue, join, etc. — match the SoCo surface PlaylistManager actually calls
   ```

   The dataclass approach gives readable state for assertions. Add fields/methods only as tests demand them; don't over-engineer.

3. **Write `tests/test_playlists.py::test_takeover_logs_cleanly`**:
   ```python
   import logging
   from mcp_sonos.playlists import PlaylistManager
   from ._fakes import SoCoFake

   def test_takeover_logs_cleanly(caplog):
       speaker = SoCoFake(player_name="Kitchen")
       def resolve_coord(spk):
           return spk.group.coordinator
       def resolve_speaker(name):
           assert name == "Kitchen"
           return speaker
       manager = PlaylistManager(
           resolve_coordinator=resolve_coord,
           resolve_speaker=resolve_speaker,
           url_for_file=lambda p: f"http://test/{p}",
       )
       # Build a playlist, start it
       manager.create("morning")
       manager.add_many("morning", [{"url": "http://test/a.mp3", "title": "A"}])
       manager.play(speaker, "morning")
       # Simulate external takeover by editing the fake's transport
       speaker._transport = {"current_transport_state": "PLAYING"}
       speaker._track = {"uri": "http://other/takeover.mp3", "title": ""}
       # Wait for the worker to notice
       import time
       time.sleep(1.0)
       # Assertions
       assert "preempted" in caplog.text.lower() or "stopping" in caplog.text.lower()
       assert "AttributeError" not in caplog.text
   ```

   This test depends on `PlaylistManager` accepting injected resolver callables — confirm the existing constructor shape. If it doesn't, that's a tiny secondary refactor (extract the resolvers to constructor params).

4. **`pyproject.toml` additions**:
   ```toml
   [project.optional-dependencies]
   dev = [
       "pip-audit",   # added in Flight 3
       "pytest",
   ]

   [tool.pytest.ini_options]
   testpaths = ["tests"]
   ```

5. **Update CLAUDE.md** (post-completion): the "No test framework, no linter configured" line is now half-true; reword to "pytest scaffolding exists with one regression test; smoke tests still cover the integration surface."

## Files Affected
- `mcp_sonos/server.py` — significant refactor (DI / `register_tools` pattern)
- `tests/_fakes.py` — new
- `tests/__init__.py` — new (empty)
- `tests/test_playlists.py` — new
- `pyproject.toml` — `[tool.pytest.ini_options]` + `pytest` in dev extras
- `CLAUDE.md` — update post-completion to reflect new state

## Edge Cases
- **PlaylistManager doesn't expose resolvers as constructor params** today: that's a small extension to make the test feasible. If the existing constructor takes a controller, the test can wrap a fake controller around the SoCoFake.
- **Worker polling timing**: the worker polls transport state every 500 ms (per CLAUDE.md). The test's `time.sleep(1.0)` should be plenty, but flakiness is possible — use `pytest-timeout` if needed, or model the worker tick as a public method for direct invocation.
- **caplog level**: pytest captures from `WARNING` by default at root; set `caplog.set_level(logging.INFO)` to capture the playlist's `info` logs.
- **Scope creep**: don't expand fake surface beyond what this one test needs. F1 regression is the goal; future tests will grow the fake.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] `pytest` passes locally with no live hardware
- [ ] Smoke tests still pass against live hardware
- [ ] CLAUDE.md updated to describe the new test scaffolding
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
