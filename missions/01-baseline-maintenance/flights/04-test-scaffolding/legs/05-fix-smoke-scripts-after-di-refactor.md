# Leg: 05-fix-smoke-scripts-after-di-refactor

**Status**: completed
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Restore both smoke scripts to functional state. Leg 02's DI refactor (move tool registration from module top-level into `register_tools(mcp, controller)` called from `main()`) inadvertently broke both `smoke_test.py` and `playlist_smoke.py` — they import `mcp`/`controller` directly from `mcp_sonos.server` and open `Client(mcp)` without ever constructing a controller or registering tools. This leg is a **scope expansion** added mid-flight (after Leg 04 attempted to verify the `say()` fix and discovered the regression).

## Context
Surfaced during Leg 04's attempt at hardware verification of the `say()` fix:
- `smoke_test.py:22` imports `mcp` from `mcp_sonos.server` and runs `Client(mcp)` against it without ever calling `main()`. After Leg 02, the imported `mcp` instance has zero tools → `fastmcp.exceptions.ToolError: Unknown tool: 'list_speakers'`
- `playlist_smoke.py:35` imports `mcp, controller` from `mcp_sonos.server`. After Leg 02 removed module-level `controller = SonosController()`, this import raises `ImportError`

Both regressions are in the smoke scripts, NOT in `mcp_sonos/` source. The pytest suite (Leg 03's 8 tests + Leg 04's 2 tests = 10 tests) is unaffected. The fix is mechanical: construct a `SonosController`, call `register_tools(mcp, controller)`, THEN open `Client(mcp)`.

Captured in mission Known Issues by Leg 04. Adding as Leg 05 of Flight 04 — same flight that introduced the regression should close it.

## Inputs
- `smoke_test.py` — top-of-file imports + `Client(mcp)` usage
- `playlist_smoke.py` — top-of-file imports + `Client(mcp)` usage
- `mcp_sonos/server.py::register_tools` (Leg 02) — the function that needs to be called

## Outputs
- Both smoke scripts can be run end-to-end against live hardware again
- Both scripts construct a `SonosController` and call `register_tools(mcp, controller)` before `Client(mcp)`
- No source-code changes in `mcp_sonos/`

## Acceptance Criteria
- [x] `smoke_test.py` imports include `from mcp_sonos.controller import SonosController` and `from mcp_sonos.server import mcp, register_tools`
- [x] `smoke_test.py` constructs `controller = SonosController()` and calls `register_tools(mcp, controller)` before any `Client(mcp)` usage
- [x] `playlist_smoke.py` does the same — does NOT import `controller` from `mcp_sonos.server` (which no longer exists)
- [x] `playlist_smoke.py` constructs its own `controller` locally, calls `register_tools(mcp, controller)`, then opens the Client
- [x] Existing `SONOS_IPS` setdefault block from Leg 01 stays in place at the top of both scripts (before the SonosController construction so discovery uses the deterministic IPs)
- [x] `.venv/bin/python -m py_compile smoke_test.py playlist_smoke.py` — clean
- [ ] If hardware is reachable: `.venv/bin/python smoke_test.py` and `.venv/bin/python playlist_smoke.py` run without ImportError or ToolError. `smoke_test.py`'s `say()` path should now pass thanks to Leg 04's fix; if it still fails, the failure mode should be different from "Unknown tool" — **Hardware unreachable from this session** (`ping -c1 -W1` against 192.168.1.51-55 all UNREACHABLE); live re-run deferred to post-handoff verification.

## Verification Steps
- `.venv/bin/python -c "import ast; ast.parse(open('smoke_test.py').read())"` — clean
- `.venv/bin/python -c "import ast; ast.parse(open('playlist_smoke.py').read())"` — clean
- `grep -n "register_tools" smoke_test.py playlist_smoke.py` — both files have at least one hit
- `grep -n "from mcp_sonos.server import.*controller" playlist_smoke.py` — zero hits (no longer importing the module-level `controller` symbol that doesn't exist)
- If hardware reachable: re-run both smoke scripts and capture wall-clock + outcome in flight log

## Implementation Guidance

1. **`smoke_test.py`** — current top imports include `from mcp_sonos.server import mcp` (line ~22). Update to:
   ```python
   from mcp_sonos.controller import SonosController
   from mcp_sonos.server import mcp, register_tools

   # ... after the SONOS_IPS setdefault block, BEFORE any Client(mcp) usage:
   controller = SonosController()
   register_tools(mcp, controller)
   ```
   Place the `controller` construction and `register_tools` call in `main()` (if the script has one) or at module top level after the env setdefault. The exact placement should match the script's existing structure — pick the spot that minimizes diff churn while ensuring tools are registered before `Client(mcp)` is opened.

2. **`playlist_smoke.py`** — similar fix. The current `from mcp_sonos.server import mcp, controller` (line ~35) must change because `controller` no longer exists at module level. Replace with:
   ```python
   from mcp_sonos.controller import SonosController
   from mcp_sonos.server import mcp, register_tools

   # ... after the SONOS_IPS setdefault block:
   controller = SonosController()
   register_tools(mcp, controller)
   ```
   Any subsequent code that references `controller` (the module-level one) now uses the local `controller` variable. Should be a small rename or no-rename depending on the script's structure.

3. **Verify** per the AC list. If hardware is reachable, run both smoke scripts and confirm:
   - `smoke_test.py` no longer ToolErrors; `say()` should now pass thanks to Leg 04's fix
   - `playlist_smoke.py` no longer ImportErrors; playlist round-trip works as before

## Files Affected
- `smoke_test.py` — top-level imports + early-execution block
- `playlist_smoke.py` — top-level imports + early-execution block

## Edge Cases
- **`controller` references later in the scripts**: if a script references `controller` after the import (rather than just opening `Client(mcp)`), the local variable name has to match. Likely just `controller` since that's the natural name; the rename is null in most cases.
- **`main()` ordering**: if a script has a `main()` function and the `Client(mcp)` is opened inside it, the `controller = SonosController()` and `register_tools(...)` must execute BEFORE the `Client(mcp)` is opened. Placement matters: at the top of `main()` or just after env setdefault.
- **Side effects of `SonosController()`**: constructing it now (with the SONOS_IPS env var pre-set by Leg 01) will start the AudioHost (TCP bind) and trigger speaker discovery. This is the same side-effect surface the scripts had pre-Leg-02 (when `controller` was module-level). No new behavior.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] If hardware reachable: smoke scripts re-run and captured in flight log
- [x] Update `../flight-log.md` with Leg 05 progress entry + acknowledge this closes the regression Leg 04 surfaced
- [x] Mission Known Issues entry for the smoke-script regression: mark resolved
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
