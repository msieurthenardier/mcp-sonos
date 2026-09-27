# Squawk 0001: CLAUDE.md Versioning quotes a stale `__version__`

**Status**: open
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-26
**Completed**: —

## Report
CLAUDE.md's Versioning section says `__version__` is currently `"0.2.0"`; the code is at `"0.3.0"`.
Same class of drift as Mission 03 finding I-9 (a hardcoded number in prose). Fix by removing the
literal — point at `mcp_sonos/__init__.py` as the source of truth rather than quoting its value.
Found during the Mission 03 / Flight 01 review and debrief.

## Evidence
- `CLAUDE.md:254` — "Single source of truth: `mcp_sonos/__init__.py` → `__version__` (currently `"0.2.0"`)."
- `mcp_sonos/__init__.py:3` — `__version__ = "0.3.0"`
- `CLAUDE.md:267` ("took it `0.1.0 → 0.2.0`") is a historical example, not a current-state claim — leave it.

## Corrective Action

## Verification
`grep -n 'currently' CLAUDE.md` shows no quoted version literal in the Versioning section;
`pytest tests/test_version.py` still passes.

## Sign-Off
