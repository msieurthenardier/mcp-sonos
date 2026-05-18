# Leg: 06-restrict-play-url-schemes

**Status**: ready
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
Reject non-`http`/`https` URL schemes at the `play_url`, `playlist_add`, and `playlist_add_many` tool boundaries (Finding F14 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `controller.py:155-165` forwards any string to `coord.play_uri`. Schemes like `file://`, `gopher://`, custom `x-rincon-*://` etc. pass through to the Sonos speaker.
- The Sonos speaker rejects most of these, but the host doesn't pre-fetch the URL — so there's no host-side SSRF — just an undefined contract and an unhelpful error path (`701: Illegal MIME-Type`).
- Architect's recommendation: a Pydantic `Field` validator on URL parameters at the tool surface (`server.py`) so the agent sees a clean MCP validation error rather than a SoCo exception.
- Same surface applies to `playlist_add(name, url, ...)` and `playlist_add_many(name, items[])` (each item carries a `url`).

## Inputs
- `mcp_sonos/server.py` `play_url`, `playlist_add`, `playlist_add_many` tool definitions
- (Optionally) corresponding `playlists.py` model fields

## Outputs
- `play_url`, `playlist_add`, and `playlist_add_many` reject URLs whose scheme is not `http` or `https` with a clear validation error
- HTTP/HTTPS URLs continue to work

## Acceptance Criteria
- [ ] `play_url("Kitchen", "file:///etc/passwd")` returns a validation error
- [ ] `play_url("Kitchen", "gopher://example.com/")` returns a validation error
- [ ] `play_url("Kitchen", "http://...")` and `play_url("Kitchen", "https://...")` still work
- [ ] `playlist_add(..., url="file:///...")` and `playlist_add_many` with a bad item URL both reject
- [ ] No regression in playlist smoke tests

## Verification Steps
- Manual: call `play_url` with a `file://` URL via an MCP client; observe the validation error in the MCP response.
- Manual: call with a valid `http://...mp3` URL; observe success.
- `playlist_smoke.py` passes against live hardware.

## Implementation Guidance

1. **Choose validation site**. Tool-side (Pydantic) is preferred per the Architect — agent sees the error in the MCP response.

2. **Create a small validator function** or use a Pydantic `AfterValidator` / regex:
   ```python
   from urllib.parse import urlparse
   def _validate_http_url(u: str) -> str:
       scheme = urlparse(u).scheme.lower()
       if scheme not in ("http", "https"):
           raise ValueError(f"URL scheme must be http or https; got {scheme!r}")
       return u
   ```

3. **Apply to**:
   - `play_url` `url` parameter (`server.py`)
   - `playlist_add` `url` parameter
   - `playlist_add_many` items — depending on item shape, validate `url` per item

4. **If `playlist_add_many` items are typed via a Pydantic model**, add the validator to that model.

## Files Affected
- `mcp_sonos/server.py` — three tool definitions
- (Possibly) `mcp_sonos/playlists.py` — if there's a shared `PlaylistItem`-like model

## Edge Cases
- **Empty string**: `urlparse("").scheme` → `""`, rejected. Good.
- **URLs without scheme** (e.g., `example.com/song.mp3`): `urlparse` returns `scheme=""`, rejected with a clear error. Better than letting Sonos receive a malformed URI.
- **Mixed case scheme** (`HTTP://...`): lowercase before comparison.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Playlist smoke test passes
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
