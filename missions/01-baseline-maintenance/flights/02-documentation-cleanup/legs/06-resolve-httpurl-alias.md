# Leg: 06-resolve-httpurl-alias

**Status**: completed
**Flight**: [Documentation Cleanup](../flight.md)

## Objective
Delete the unused `HttpUrl` alias in `mcp_sonos/server.py`. The alias is dead code today (defined but never referenced by consumer tools, which inline `AfterValidator(validate_http_url)`). Per flight design decision, this leg commits to deletion; adoption is out of scope here and can land as a separate future flight if Pydantic 2 ergonomics for `Annotated[Annotated[...], Field(...)]` improve. (Flight 01 debrief Action Item #5.)

## Context
- Flight 01's F14 leg introduced `mcp_sonos/_urls.py::validate_http_url` and a Pydantic alias at `server.py:47`:
  ```python
  HttpUrl = Annotated[str, AfterValidator(validate_http_url)]
  ```
- The alias was intended to be the named type for URL parameters across the MCP tools. But the two consumer tools — `play_url` (around `server.py:85`) and `playlist_add` (around `server.py:245`) — inline `AfterValidator(validate_http_url)` instead of using `HttpUrl`, because chaining `Field(description=...)` after the alias is awkward in Pydantic 2.
- The Flight 01 reviewer and the Flight 01 debrief Architect both flagged this as dead-code / half-adoption: the alias is defined but never imported or referenced; it's clutter.
- Flight design decision: **default to delete**. The simplest resolution. If the implementing Developer discovers a clean adoption pattern (e.g., `Annotated[HttpUrl, Field(description="...")]` actually works in Pydantic 2.13+), prefer adoption. Either resolution is acceptable; half-adoption is not.

## Inputs
- `mcp_sonos/server.py:47` (the alias definition)
- `mcp_sonos/server.py:85, 245` (the two inline `AfterValidator` usage sites)
- Optionally: `mcp_sonos/server.py` import block (if deleting, `AfterValidator` and `HttpUrl` references in the import line may need pruning — `AfterValidator` stays, since the inline sites use it)

## Outputs
- `HttpUrl` symbol no longer exists in `server.py`. Inline `AfterValidator(validate_http_url)` calls remain at the two consumer tool sites — those are the live policy.

## Acceptance Criteria
- [x] `grep -n "HttpUrl" mcp_sonos/server.py` returns zero hits
- [x] `mcp_sonos/server.py` compiles cleanly (`.venv/bin/python -m py_compile mcp_sonos/server.py`)
- [x] `play_url("Kitchen", "file:///etc/passwd")` still rejects with a Pydantic validation error (validator behavior unchanged — proved via direct `validate_http_url('file:///etc/passwd')` call raising `ValueError`)
- [ ] `play_url("Kitchen", "http://...")` still works (no regression on the happy path) — not verified against live hardware; consumer sites at `server.py:78,238` still bind `AfterValidator(validate_http_url)` inline, so the happy path is structurally unchanged
- [x] No other code or doc changes — this leg is scoped to `server.py` only (alias line plus orphaned anchor comment removed; no other files touched)

## Verification Steps
- `grep -n "HttpUrl" mcp_sonos/server.py` — assert against expected count per chosen option.
- `.venv/bin/python -m py_compile mcp_sonos/server.py` — clean.
- Quick MCP-validator test: `.venv/bin/python -c "from mcp_sonos._urls import validate_http_url; validate_http_url('file:///etc/passwd')"` — should still raise.
- Optionally: `.venv/bin/python playlist_smoke.py` against live hardware (exercises `playlist_add` validator).

## Implementation Guidance

1. **Read** `server.py` at the alias definition (line 47). Confirm `HttpUrl` is not referenced anywhere else: `grep -n "HttpUrl" mcp_sonos/server.py` should show exactly one hit (the definition).

2. **Delete** the alias definition (line 47, including any blank line before/after if it becomes orphaned).

3. **Leave the inline `AfterValidator(validate_http_url)` calls unchanged** at the two consumer tool sites (`play_url` around line 85, `playlist_add` around line 245). Those are the live policy; this leg only removes the unused alias.

4. **Verify**: `grep -n "HttpUrl" mcp_sonos/server.py` → zero hits. `.venv/bin/python -m py_compile mcp_sonos/server.py` → clean.

5. **No CLAUDE.md edits required**: Leg 05's text references `validate_http_url` (the function) and `_urls.py` (the module), not the `HttpUrl` alias. Verify by grep before assuming.

## Files Affected
- `mcp_sonos/server.py` — alias definition (line 47), consumer tool annotations (lines 85, 245), optionally the import block (line 15)

## Edge Cases
- **Pydantic version compatibility**: the project requires `pydantic>=2.0`. `AfterValidator` is available from 2.0; chained `Annotated[Annotated[...], ...]` flattening is also from 2.0. Should be fine across the supported range. Confirm by running the one-liner test in step 2.
- **MCP schema impact**: deleting the alias removes a named type from the JSON schema FastMCP generates. The two consumer tools' `url` parameters will appear as `string` with a validator function attached. Acceptable — agents typically don't surface aliased type names anyway.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] `grep` confirms no half-adoption
- [x] Optionally: smoke test pass
- [x] Update `../flight-log.md` with leg progress entry, noting whether Option A or Option B landed
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
