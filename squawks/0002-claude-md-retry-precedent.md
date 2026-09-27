# Squawk 0002: Name `_retry.py` as a second shared-helper precedent in CLAUDE.md

**Status**: open
**Type**: servicing
**Severity**: routine
**Reported**: 2026-09-26
**Completed**: —

## Report
CLAUDE.md "When extending" cites only `mcp_sonos/_urls.py` as the example of a single shared
module imported at every surface. Mission 03 / Flight 01 (I-3) added `mcp_sonos/_retry.py` —
a cycle-free leaf module whose `with_stale_coord_retry` takes DI callbacks (`invalidate`, `resolve`)
so `controller.py` and `playlists.py` share one implementation while keeping their own contracts.
A second precedent helps the next contributor adding a cross-cutting helper. Doc-only.

## Evidence
- `CLAUDE.md` "When extending" — "Cross-cutting input validation (defense-in-depth)" bullet names only `_urls.py::validate_http_url`
- `mcp_sonos/_retry.py:with_stale_coord_retry(coord, action, invalidate, resolve)`; call sites in `controller.py` (`_say`/`_say_one`) and `playlists.py::_play_via_queue`

## Corrective Action

## Verification
`grep -n '_retry.py' CLAUDE.md` finds the new mention in "When extending"; wording matches the
describe-don't-prescribe tone of the adjacent bullets.

## Sign-Off
