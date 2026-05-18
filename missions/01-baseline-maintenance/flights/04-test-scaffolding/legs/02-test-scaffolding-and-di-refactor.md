# Leg: 02-test-scaffolding-and-di-refactor

**Status**: completed
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Land the architectural backbone of the test scaffolding: (a) defer `SonosController()` construction from module-level `server.py:33` so imports don't bind a TCP port; (b) introduce `register_tools(mcp, controller)` factory so tools are wired to a controller passed in; (c) create `tests/_fakes.py::SoCoFake` with the minimal surface the controller and playlists actually call; (d) add pytest config to `pyproject.toml` and `pytest` to the existing `[dev]` extras. **NO unit tests in this leg** — those land in Leg 03 against this scaffolding.

## Context
- Per `mission_sonos/server.py:34`: `controller = SonosController()` at module top-level. `SonosController.__init__` calls `self.audio.start()` which binds a TCP port. Any import of `mcp_sonos.server` therefore starts a network service — including pytest collection.
- CLAUDE.md `## Architecture` claims `SonosController` is "MCP-agnostic, unit-testable." Until this leg lands, that claim is aspirational.
- Flight 03's `[dev]` optional-dependencies block (`pyproject.toml`) currently contains `pip-audit`. Per Flight 03 debrief recommendation, add `pytest` to the SAME `[dev]` list — don't split into a separate `[test]` extra.
- The flight design picked `register_tools(mcp, controller)` over a `get_controller()` factory pattern — keeps DI explicit and avoids implicit module-level state.

## Inputs
- `mcp_sonos/server.py` — top-of-file imports + the 32 `@mcp.tool` definitions + a module-level `controller = SonosController()`
- `mcp_sonos/controller.py` — `SonosController` class (untouched in this leg)
- `pyproject.toml` — `[dev]` optional-deps block (extend) + add `[tool.pytest.ini_options]`
- New: `tests/_fakes.py`, `tests/__init__.py`, `tests/conftest.py` (if needed)

## Outputs
- `python -c "import mcp_sonos.server"` does NOT bind a TCP port (no `audio_host` thread started)
- `register_tools(mcp: FastMCP, controller: SonosController) -> None` exists in `server.py`; called from `main()` after constructing the controller
- Module-level `mcp = FastMCP(...)` retained (controller-independent at import)
- `tests/_fakes.py::SoCoFake` exists with the surface listed in flight design decisions
- `tests/__init__.py` exists (empty marker file)
- `tests/conftest.py` exists (empty stub — pre-empts pytest import-discovery issues in Leg 03)
- `mcp_sonos/playlists.py::PlaylistManager` exposes an optional always-on `_iteration_event: threading.Event` (set after each worker poll cycle) so tests can wait on iteration progress deterministically instead of `time.sleep`
- `pyproject.toml` `[tool.pytest.ini_options]` sets `testpaths = ["tests"]`; `[dev]` extra includes `pytest`
- `.venv/bin/pip install -e ".[dev]"` succeeds and installs pytest alongside pip-audit
- `.venv/bin/pytest` runs (may collect 0 tests in this leg — Leg 03 adds them)

## Acceptance Criteria
- [x] `mcp_sonos/server.py` has NO module-level `controller = SonosController()` — replaced with `def register_tools(mcp, controller): ...` that defines the 32 tools as closures over `controller`
- [x] Module-level `mcp = FastMCP(...)` is retained (controller-independent at import). **The existing `name="sonos"` AND the full `instructions=...` multi-line string at `server.py:21-30` are preserved verbatim — no rewording, no truncation** (confirmed via `diff` of lines 21-31 against `HEAD`: empty)
- [x] `mcp_sonos/server.py::main()` constructs the controller, calls `register_tools(mcp, controller)`, then `mcp.run()`
- [x] `python -c "import mcp_sonos.server"` exits 0 with NO side effects (no port bind, no SSDP discovery thread)
- [ ] `python -m mcp_sonos.server` still starts the MCP server end-to-end (no functional regression) — **hardware-dependent; deferred to reviewer / smoke run**
- [x] `tests/_fakes.py::SoCoFake` dataclass exists; supports the surface in flight design (`player_name`, `uid`, `ip_address`, `is_visible()`, `group.coordinator`, `group.members`, `get_current_transport_info()`, `get_current_track_info()`, `play_uri`, `pause`, `stop`, `next`, `previous`, `volume` property, `mute`/`unmute`, `unjoin`, `join`, `add_to_queue`, `clear_queue`)
- [x] `tests/_fakes.py` does NOT import `soco` — use string forward references (`"SoCoFake"`) for self-references; the fake is independent of the real SoCo library
- [x] `tests/__init__.py` exists (empty)
- [x] `tests/conftest.py` exists (empty stub — pre-empts import-discovery issues)
- [x] `mcp_sonos/playlists.py::PlaylistManager.__init__` initializes `self._iteration_event = threading.Event()`; the worker's inner poll loop calls `self._iteration_event.set()` **at the top of each iteration** (before any break/continue/sleep). Always-on (zero runtime cost; production code never reads it)
- [x] `pyproject.toml` `[project.optional-dependencies] dev` extra is `["pip-audit", "pytest"]` (both, in alphabetical order or any consistent order)
- [x] `pyproject.toml` has `[tool.pytest.ini_options]` block with `testpaths = ["tests"]`
- [x] `.venv/bin/pip install -e ".[dev]"` succeeds
- [x] `.venv/bin/pytest` runs (exits 0 even if "no tests ran" — that's normal for this leg)
- [ ] `.venv/bin/python smoke_test.py` and `.venv/bin/python playlist_smoke.py` still work against live hardware (no functional regression at runtime) — **hardware-dependent; deferred**

## Verification Steps
- `grep -n "^controller = SonosController" mcp_sonos/server.py` returns no hits
- `grep -n "def register_tools" mcp_sonos/server.py` returns at least one hit
- `grep -c "Use 'all' as the target" mcp_sonos/server.py` returns `1` (sentinel from the original `instructions=...` block — confirms verbatim preservation)
- `python -c "import mcp_sonos.server; print('imports clean')"` — exits 0, no extra output beyond the print
- `ls tests/` shows `__init__.py`, `conftest.py`, and `_fakes.py`
- `.venv/bin/python -c "from tests._fakes import SoCoFake; f = SoCoFake(player_name='Test'); print(f.player_name)"` exits with "Test"
- `grep -n "import soco" tests/_fakes.py` returns no hits
- `.venv/bin/pip-audit --version` AND `.venv/bin/pytest --version` both work after `pip install -e ".[dev]"`
- `.venv/bin/python -m mcp_sonos.server` starts (Ctrl-C to stop; smoke can verify end-to-end if hardware reachable)

## Implementation Guidance

1. **Refactor `mcp_sonos/server.py`** to defer controller construction. **Keep the module-level `mcp = FastMCP(...)` instance** (it's controller-independent — safe at import time). Only `SonosController()` construction defers. Suggested shape:
   ```python
   # server.py
   from fastmcp import FastMCP
   from .controller import SonosController

   mcp = FastMCP("sonos", instructions=...)  # KEEP this at module level — no controller dep

   def register_tools(mcp: FastMCP, controller: SonosController) -> None:
       @mcp.tool
       def list_speakers() -> ...:
           return controller.list_speakers()
       # ... all 32 tools defined here as closures over controller ...

   def main() -> None:
       controller = SonosController()
       register_tools(mcp, controller)
       mcp.run()

   if __name__ == "__main__":
       main()
   ```
   - No `create_app` indirection — direct module-level `mcp` + late `register_tools` is the clean shape. FastMCP 3.3.1 supports late `@mcp.tool` registration (verified during design review).
   - The tool functions can be closures (cleanest for DI) OR methods on a small `Tools` class — pick closures, they align with the existing `@mcp.tool` decorator style.
   - Keep all existing `Annotated[..., Field(description=...)]` parameter annotations exactly as-is.

2. **Create `tests/__init__.py`** as an empty file.

3. **Create `tests/_fakes.py`** with `SoCoFake`. Suggested shape:
   ```python
   from dataclasses import dataclass, field
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
       _volume: int = 40
       _mute: bool = False

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

       def next(self) -> None: pass
       def previous(self) -> None: pass

       @property
       def volume(self) -> int:
           return self._volume

       @volume.setter
       def volume(self, v: int) -> None:
           self._volume = int(v)

       @property
       def mute(self) -> bool:
           return self._mute

       @mute.setter
       def mute(self, v: bool) -> None:
           self._mute = bool(v)

       def unjoin(self) -> None:
           # Fake doesn't model multi-group state — just refresh group-of-one
           self.group = FakeGroup(coordinator=self, members=[self])

       def join(self, other: "SoCoFake") -> None:
           # Simplistic: this becomes a member of other's group
           self.group = FakeGroup(coordinator=other, members=[other, self])
           other.group = FakeGroup(coordinator=other, members=[other, self])

       # add_to_queue, clear_queue as no-ops or simple list-state if a test needs them
       def add_to_queue(self, uri_or_track) -> int: return 1
       def clear_queue(self) -> None: pass
   ```
   - Don't over-engineer. Add fields/methods only as tests in Leg 03 demand them.
   - Use `unittest.mock.MagicMock` for any surface a test needs but the fake doesn't model — but try to keep tests reading the fake's explicit state, not mock call counts.

4. **`pyproject.toml`** additions:
   ```toml
   [project.optional-dependencies]
   dev = [
       "pip-audit",
       "pytest",
   ]

   [tool.pytest.ini_options]
   testpaths = ["tests"]
   ```
   - Re-install: `.venv/bin/pip install -e ".[dev]"`

5. **`tests/conftest.py`**: create as an empty file. Pre-empts any pytest import-discovery edge case in Leg 03 where `from tests._fakes import SoCoFake` might fail without conftest hints. Zero cost.

6. **Add `_iteration_event` to `PlaylistManager`** in `mcp_sonos/playlists.py`:
   ```python
   # In PlaylistManager.__init__, alongside the other state:
   self._iteration_event = threading.Event()

   # In the worker's INNER poll loop (the `while not session.stop_event.is_set():` around playlists.py:357
   # — the wait-for-track-end loop, NOT the outer track loop):
   #   At the TOP of the loop body, BEFORE any break/continue/sleep:
   while not session.stop_event.is_set():
       self._iteration_event.set()  # Test-observability hook — production code never waits on this.
       if session.skip_event.is_set():
           ...
   ```
   - **Placement matters**: set at the TOP of the loop body, not after `time.sleep(POLL_INTERVAL)`. The latter is bypassed by the break paths (skip @ ~363, back @ ~375, takeover @ ~398) and `continue` paths, which would make Leg 03's test hang when it waits for an iteration after triggering one of those events.
   - Always-on (zero cost; production code never `wait()`s on it). Tests use `manager._iteration_event.wait(timeout=2.0)` then `manager._iteration_event.clear()` for the next iteration.
   - Document with a one-line comment: `# Test-observability hook — production code never waits on this.`

7. **Verify** per the AC list — most importantly, `python -c "import mcp_sonos.server"` should NOT bind a port.

## Files Affected
- `mcp_sonos/server.py` — significant refactor (DI pattern; module-level controller removed; module-level `mcp` kept)
- `mcp_sonos/playlists.py` — add `self._iteration_event` to `PlaylistManager.__init__` + `set()` in the worker loop
- `tests/__init__.py` — new, empty
- `tests/conftest.py` — new, empty
- `tests/_fakes.py` — new, SoCoFake
- `pyproject.toml` — `[dev]` extras + `[tool.pytest.ini_options]`

## Edge Cases
- **FastMCP late `@mcp.tool` registration**: verified at design review against `fastmcp==3.3.1`. The decorator mutates the `FastMCP` instance; calling it inside `register_tools(mcp, controller)` works. No divert path needed.
- **Smoke tests need a running server** to verify they're unaffected by the refactor — that's a hardware-dependent post-leg verification. The leg's primary AC is hardware-free (import + pytest no-bind).
- **`controller.py` import side effects**: `_voices_cache_dir()` runs at module import. That's fine — no network. `tts.py`, `audio_host.py`, `playlists.py` are all import-clean. Only `server.py`'s module-level `SonosController()` was triggering side effects.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Smoke tests still pass (or known-issue-only failures unchanged)
- [x] Update `../flight-log.md` with leg progress entry
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
