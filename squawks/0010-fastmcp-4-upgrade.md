# Squawk 0010: upgrade FastMCP 3.x to 4.x (MCP 2026-07-28 spec)

**Status**: completed
**Type**: servicing
**Severity**: routine
**Reported**: 2026-10-11
**Completed**: 2026-10-11

## Report
MCP spec 2026-07-28 is now the current revision. It is stateless: the
`initialize` handshake, sessions and `ping` are removed. FastMCP 4, built on
the `mcp` 2.x SDK, implements it, and older-protocol clients keep working.
We pin `fastmcp>=3.0,<4`, so the server can't speak the current protocol.
We're doing this now, ahead of the voice-playlist reap-survival sortie, so
that work is built on the current SDK.

## Evidence
- `pyproject.toml` — `"fastmcp>=3.0,<4"`. Installed: fastmcp 3.3.1 and
  mcp 1.27.1.
- PyPI: fastmcp 4.0.0 stable since 2026-08-31, latest 4.1.0 (2026-10-08);
  mcp 2.3.0. Both are `requires_python >=3.10`, which matches ours.
- FastMCP v4 notes (https://gofastmcp.com/development/v4-notes): most v3
  apps upgrade with no code changes. The main break is removing push-style
  sampling (`ctx.sample`).
- `mcp_sonos/server.py` uses no `Context`, sampling, elicitation, roots or
  logging. A grep finds nothing.
- Our FastMCP usage: `server.py` (`FastMCP(..., version=__version__)`,
  `@mcp.tool`, `Annotated[..., Field(...)]` with `AfterValidator`),
  `tests/test_playlist_voice_items.py` (`Client`, `FastMCP`,
  `fastmcp.exceptions.ToolError`), every `*_smoke.py` (`fastmcp.Client`
  in-process).
- `tests/test_version.py` checks that `mcp.version == __version__`. This
  wiring must still hold under v4.

## Corrective Action
Bumped the pin to `fastmcp>=4.0,<5`. Resolved fastmcp 4.1.0 (plus fastmcp-slim
4.1.0) and mcp 2.3.0. No server or tool code changes were needed.
Files touched:
- `pyproject.toml`: pin `fastmcp>=4.0,<5`.
- `mcp_sonos/__init__.py`: `__version__` 0.6.0 -> 0.6.1.
- `tests/test_version.py`: expect 0.6.1; the "not the framework version" guard
  now compares against `fastmcp.__version__` and rejects `3.`/`4.` prefixes.
- `CLAUDE.md`: Versioning section wording (framework is now 4.x; guard no longer says "3.x").
- No change to `server.py` or the smoke scripts (all compile; `fastmcp.Client(mcp)` and
  `result.data` are unchanged in v4).

## Verification
Results (developer run, 2026-10-11):
- `.venv/bin/pip install -e '.[dev]'` -> fastmcp 4.1.0, mcp 2.3.0 (`pip show`).
- `timeout 600 .venv/bin/python -m pytest -q` -> 213 passed (before and after the version bump).
- `py_compile` on smoke_test.py and all `*_smoke.py`: OK. They use `fastmcp.Client(mcp)`
  and `result.data`, which v4's `CallToolResult` still provides.
- Stdio: `fastmcp.Client(StdioTransport(.venv/bin/python -m mcp_sonos.server))` listed 35 tools,
  matching the 35 `@mcp.tool` declarations in server.py. The server started with no hardware access.
- Legacy handshake: raw JSON-RPC `initialize` over stdin with protocolVersion 2025-11-25 and
  2025-06-18 each got a valid result echoing that version, `serverInfo` = sonos 0.6.0, and a
  following `tools/list` returned tools.
Plan:
- `.venv/bin/pip install -e '.[dev]'` resolves fastmcp 4.x / mcp 2.x.
- `.venv/bin/python -m pytest -q` is green, including `test_version.py`.
- `.venv/bin/python -m mcp_sonos.server` starts on stdio and answers a
  modern request and a legacy `initialize` handshake.
- Hardware: `.venv/bin/python smoke_test.py` passes (operator-run, PENDING).

## Sign-Off
Independent Reviewer: `[HANDOFF:confirmed]` on 2026-10-11, with no issues.
The Reviewer ran pytest again (213 passed) and confirmed `pip show`
reports fastmcp 4.1.0 / mcp 2.3.0. Its own stdio check sent a legacy
`initialize` with protocolVersion 2025-11-25 and got `serverInfo`
`{"name":"sonos","version":"0.6.1"}`. That was taken after the bump,
superseding the Developer's pre-bump 0.6.0 reading. `FastMCP(...)` kwargs
are accepted under v4, and there are no tool signature or schema changes.
Commit: branch `squawk/0010-fastmcp-4-upgrade` (see its PR). The hardware
`smoke_test.py` run is still pending; the operator runs it before merge.
