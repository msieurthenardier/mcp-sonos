# Squawk 0002: Name `_retry.py` as a second shared-helper precedent in CLAUDE.md

**Status**: completed
**Type**: servicing
**Severity**: routine
**Reported**: 2026-09-26
**Completed**: 2026-09-27

## Report
CLAUDE.md "When extending" cites only `mcp_sonos/_urls.py` as the example of a single shared
module imported at every surface. Mission 03 / Flight 01 (I-3) added `mcp_sonos/_retry.py` —
a cycle-free leaf module whose `with_stale_coord_retry` takes DI callbacks (`invalidate`, `resolve`)
so `controller.py` and `playlists.py` share one implementation while keeping their own contracts.
A second precedent helps the next contributor adding a cross-cutting helper. Doc-only.

## Evidence
- `CLAUDE.md` "When extending" — "Cross-cutting input validation (defense-in-depth)" bullet names only `_urls.py::validate_http_url`
- `mcp_sonos/_retry.py:with_stale_coord_retry(coord, action, invalidate, resolve)`; call sites in `controller.py` (`say`'s inner `_play_clip` closure) and `playlists.py::_play_via_queue`

## Corrective Action
Added a sibling bullet, "**Cross-cutting retry behavior**", to CLAUDE.md's "When extending"
section, immediately after the existing "Cross-cutting input validation (defense-in-depth)"
bullet. It names `mcp_sonos/_retry.py::with_stale_coord_retry` as a second precedent for the
single-shared-module pattern — this time for shared logic rather than validation. Per the
squawk's evidence and a read of `_retry.py` and its two call sites, the new bullet notes:
- it's a cycle-free leaf module (needed because `controller.py` imports `playlists.py`, so
  the helper couldn't live in either without a circular import)
- its two call sites: `controller.py` (`say`) and `playlists.py`
  (`_play_via_queue`)
- the DI callbacks (`invalidate`, `resolve`) that let each caller keep its own
  cache-invalidation/re-resolution contract while sharing one retry-and-recover implementation

Review correction: an earlier draft cited a controller.py helper symbol for the announce path
that has never existed in this codebase. The actual call site is `say`'s inner `_play_clip`
closure (the all-speakers variant does not call the retry helper). Evidence and Corrective
Action above were corrected to name `say` instead.

Did not touch the "No test framework" line, the Commands section, or the Versioning section's
pre-existing uncommitted edit — out of scope per this squawk and reserved for others.

## Verification
- `grep -n '_retry.py' CLAUDE.md` → finds the new mention (the "When extending" section).
  Wording matches the describe-don't-prescribe tone of the adjacent bullets (no line numbers
  cited, present-tense description of what the code does and why).
- `timeout 300 .venv/bin/python -m pytest -q` → `78 passed in 1.51s`. Doc-only change; no
  source files touched.

## Sign-Off
**Reviewer**: Reviewer agent (Sonnet), batch review — two cycles (cycle 1 blocked 0002 on a nonexistent `_say_one` citation; fixed; cycle 2 confirmed all three)
**Verdict**: confirmed
**Commit**: `squawk: turnaround 2026-09-27` on `squawk/turnaround-2026-09-27`
