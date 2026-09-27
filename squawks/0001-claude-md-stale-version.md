# Squawk 0001: CLAUDE.md Versioning quotes a stale `__version__`

**Status**: completed
**Type**: defect
**Severity**: routine
**Reported**: 2026-09-26
**Completed**: 2026-09-27

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
Removed the quoted version literal from CLAUDE.md's Versioning section (line 254). Changed:

> Single source of truth: `mcp_sonos/__init__.py` → `__version__` (currently `"0.2.0"`).

to:

> Single source of truth: `mcp_sonos/__init__.py` → `__version__`.

This points at the code as the source of truth without quoting its value, so the doc can't
drift out of sync with `mcp_sonos/__init__.py` again. The historical example later in the same
section ("took it `0.1.0 → 0.2.0`") was left untouched per scope — it's a past-tense example,
not a current-state claim. No other part of CLAUDE.md was touched.

## Verification
- `grep -n 'currently' CLAUDE.md` → only match is line 87 ("currently playing"), an unrelated
  sentence about live playback control state, not a version literal. The Versioning section
  (line ~254) now contains no quoted version string.
- `timeout 120 .venv/bin/python -m pytest -q tests/test_version.py` → `3 passed in 1.21s`.

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review — two cycles (cycle 1 blocked 0002 on a nonexistent `_say_one` citation; fixed; cycle 2 confirmed all three)
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-27` on `squawk/turnaround-2026-09-27`
