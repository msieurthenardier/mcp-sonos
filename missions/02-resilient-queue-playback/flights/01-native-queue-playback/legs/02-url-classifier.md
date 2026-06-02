# Leg: url-classifier

**Status**: completed
**Flight**: [Native Queue Playback Path](../flight.md)

## Objective
Add a host/port-relative classifier that decides whether a URL is served by the
MCP's in-process audio host (and therefore cannot survive a reap), so Leg 3 can
route playlists to the queue path vs. the worker fallback.

## Context
- Flight DD "Classifier is host/port-relative, not a static URL predicate": an
  MCP-hosted URL is `http://{host_ip}:{port}/{file}` where host/port are resolved
  per-process at `SonosController.__init__` (`audio_host.py`). The classifier must
  take `(host_ip, port)` as input — it is NOT analogous to `validate_http_url`.
- Mission constraint: cross-cutting URL handling stays centralized (`_urls.py`).
- This leg provides the predicate only; Leg 3 composes it into the routing decision.

## Inputs
- `mcp_sonos/_urls.py` (existing `validate_http_url`).
- `mcp_sonos/audio_host.py` exposes `AudioHost.host_ip` and `AudioHost.port`.
- Leg 1 complete (queue mechanism understood).

## Outputs
- `is_mcp_hosted(url: str, host_ip: str, port: int) -> bool` in `mcp_sonos/_urls.py`.
- Unit tests in the existing pytest suite (hardware-free, synthetic host/port).

## Acceptance Criteria
- [x] `is_mcp_hosted(url, host_ip, port)` returns `True` iff the URL's host equals
      `host_ip` AND the URL's explicit port equals `port` (exact match)
- [x] An external URL on a different host → `False`
- [x] An external URL with no explicit port (e.g. `https://blog.example/a.mp3`) → `False`
- [x] An external URL sharing the host but a different port → `False`
- [x] A genuine MCP audio-host URL (`http://{host_ip}:{port}/file.mp3`) → `True`
- [x] Malformed input is handled (returns `False`, does not raise). Note: a
      non-integer port (`http://host:notaport/x`) makes `urlparse(...).port` raise
      `ValueError` — the function must swallow it. (`validate_http_url` raises by
      design; do NOT borrow its error pattern — wrap this body in try/except.)
- [x] A bare base URL with no path (`http://{host_ip}:{port}`) → `True` (acceptable)
- [x] Unit tests cover all the above, run hardware-free, and the full suite stays green

## Verification Steps
- `pytest -x -q` (or the project's configured runner) passes, including new tests
- New tests assert each acceptance bullet with synthetic host/port values

## Implementation Guidance
1. **Add `is_mcp_hosted` to `_urls.py`.**
   - Wrap the whole body in `try: ... except Exception: return False` — this
     covers `urlparse(...).port` raising `ValueError` on a non-integer port.
   - Parse with `urllib.parse.urlparse`; compare `parsed.hostname == host_ip` and
     `parsed.port == port`. `parsed.port` is `None` when absent → not a match.
     `urlparse` lowercases `hostname`; `host_ip` is always an IP literal, so no
     extra normalization is needed.
2. **Unit tests** in `tests/test_urls.py` (plain pytest functions, no fixtures —
   import directly from `mcp_sonos._urls`), matching that file's existing style.
3. Keep the predicate single-purpose; it receives a **raw URL string** (Leg 3
   classifies before building DIDL). The playlist-level "any MCP-hosted?"
   composition belongs to Leg 3.

## Edge Cases
- **Port-less external URL on same host**: must be `False` (no port match).
- **`host_ip` is an IP, external URL uses a domain**: no collision; `False`.
- **Uppercase host**: IP comparison is exact; hostnames are normalized lowercase
  by `urlparse` — fine.

## Files Affected
- `mcp_sonos/_urls.py` — add `is_mcp_hosted`
- test file for `_urls` (existing or new) — add coverage
