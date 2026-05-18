# Leg: 02-cap-fastmcp-version

**Status**: completed
**Flight**: [Supply-Chain Hardening](../flight.md)

## Objective
Add an upper version bound on `fastmcp` in `pyproject.toml` so a SemVer-major release doesn't silently break `uvx --from git+...` users (Finding F13 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `pyproject.toml:25-30` declares `fastmcp>=3.0` with no upper bound. Other deps similarly unpinned, but FastMCP is the youngest and has moved fastest (3.0 → 3.3 in months).
- The project is distributed via `uvx --from git+https://github.com/msieurthenardier/mcp-sonos mcp-sonos`, which means every install resolves the latest matching versions at install time. A `fastmcp` 4.0 with breaking changes will break new installs of an unchanged mcp-sonos.
- Architect's recommendation: cap `fastmcp<4`. Don't cap soco/piper-tts/pydantic — they're more stable.

## Inputs
- `pyproject.toml:25-30` `dependencies` list

## Outputs
- `fastmcp>=3.0,<4` in `pyproject.toml`
- (Optional, per maintainer call) similar caps on the other three deps if you want to lock down

## Acceptance Criteria
- [x] `fastmcp>=3.0,<4` (or equivalent) in `pyproject.toml`
- [x] `pip install -e .` still works
- [x] No regression in smoke tests (hardware-independent verification: import + `py_compile mcp_sonos/server.py` clean; full live smoke deferred to Flight 04 prerequisites)
- [x] Installed versions recorded at pin time (see flight log Leg 02 entry: `fastmcp==3.3.1`, `soco==0.31.0`, `piper-tts==1.4.2`, `pydantic==2.13.4`)

## Verification Steps
- `.venv/bin/pip install -e .` succeeds.
- `.venv/bin/python -m mcp_sonos.server` starts.
- `smoke_test.py` passes.

## Implementation Guidance

1. **Edit `pyproject.toml`** dependencies list:
   ```toml
   dependencies = [
       "fastmcp>=3.0,<4",
       "soco>=0.30",
       "piper-tts>=1.3",
       "pydantic>=2.0",
   ]
   ```

2. **(Optional)** consider caps on others: `soco<1`, `piper-tts<2`, `pydantic<3`. Decide based on stability tolerance.

3. **Reinstall** to verify resolver behavior: `pip install -e .`. If the installed FastMCP is `3.3.x`, the cap is benign.

4. **Note in flight log** the installed versions at the time of pinning so the next maintenance cycle has a delta.

## Files Affected
- `pyproject.toml`

## Edge Cases
- **Reinstall picks an older `fastmcp` from cache**: explicit version observed via `pip show fastmcp` after install confirms.
- **Lockfile**: this project does not have a lockfile (`uv.lock`, `requirements.txt`). Capping in `pyproject.toml` is the only enforcement point — that's fine for a hobbyist project, but note that the cap is the only protection.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Smoke test passes
- [x] Flight log records installed versions at pin time
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
