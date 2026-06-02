# Leg: version-reporting

**Status**: completed
**Flight**: [Native Queue Playback Path](../flight.md)

## Objective
Make the MCP report its own version (not FastMCP's), from a single source of truth,
and bump it to 0.2.0 to reflect the new native-queue capability.

## Context
- Debrief finding: `FastMCP(name="sonos", ...)` passes no `version=`, so the
  `initialize` handshake advertises `mcp.version == "3.3.1"` — FastMCP's framework
  version, not the project's. `pyproject.toml` says `0.1.0` but nothing wires it.
- Fix scope is intentionally small; post-debrief add-on to Flight 1.

## Acceptance Criteria
- [x] `mcp_sonos/__init__.py` defines `__version__ = "0.2.0"` (single source of truth)
- [x] `pyproject.toml` derives its version from that source (hatchling dynamic version:
      `dynamic = ["version"]` + `[tool.hatch.version] path = "mcp_sonos/__init__.py"`),
      so the two cannot drift
- [x] `mcp_sonos/server.py` passes `version=__version__` into `FastMCP(...)`
- [x] A test asserts `mcp.version == mcp_sonos.__version__` (so a future bump that
      forgets the wiring fails the suite)
- [x] `python -c "import mcp_sonos; print(mcp_sonos.__version__)"` prints `0.2.0`, and
      the running server's `mcp.version` is `0.2.0` (not `3.3.1`)
- [x] Full suite green
- [x] Project `CLAUDE.md` documents the versioning convention: single source of
      truth is `mcp_sonos/__init__.py::__version__`; `pyproject.toml` derives it via
      hatchling dynamic version; `FastMCP(version=__version__)` advertises it in the
      MCP handshake; bump it on meaningful behavior changes; the guard test pins the wiring

## Implementation Guidance
1. Add `__version__ = "0.2.0"` to `mcp_sonos/__init__.py`.
2. In `pyproject.toml`: remove the static `version = "0.1.0"` line, add `dynamic =
   ["version"]` to `[project]`, and add `[tool.hatch.version]` with
   `path = "mcp_sonos/__init__.py"`. Confirm the package still imports and (if quick)
   that `python -m build` / `pip install -e .` resolves the version — no CI, so verify
   locally with at least the import check.
3. In `server.py`: `from . import __version__` and add `version=__version__` to the
   `FastMCP(...)` call.
4. Add a small test (e.g. `tests/test_version.py`) asserting `mcp.version ==
   __version__ == "0.2.0"`.

## Edge Cases
- **Editable-install staleness**: prefer reading `__version__` directly (not
  `importlib.metadata.version`) for the FastMCP wiring, so the running server reflects
  the source file regardless of when the package was last installed.

## Files Affected
- `mcp_sonos/__init__.py`, `pyproject.toml`, `mcp_sonos/server.py`, `tests/test_version.py`
