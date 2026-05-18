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

**Defence in depth**: validate at *both* the tool surface (clean MCP error for agents) AND the controller/playlist surface (catches non-MCP callers — future test scaffolding in Flight 4, automation scripts, anything that imports the controller directly). Same validator function reused at both sites.

1. **Create the validator** in `mcp_sonos/_urls.py` (or inline in `controller.py` if you'd rather keep modules light):
   ```python
   from urllib.parse import urlparse
   _ALLOWED_SCHEMES = {"http", "https"}
   def validate_http_url(u: str) -> str:
       scheme = urlparse(u).scheme.lower()
       if scheme not in _ALLOWED_SCHEMES:
           raise ValueError(f"URL scheme must be http or https; got {scheme!r}")
       return u
   ```

2. **At the tool surface (`server.py`)** — Pydantic `AfterValidator` so the MCP response carries a clean validation error:
   ```python
   from pydantic import AfterValidator
   from ._urls import validate_http_url

   HttpUrl = Annotated[str, AfterValidator(validate_http_url)]

   @mcp.tool
   def play_url(speaker: SpeakerName, url: HttpUrl, ...): ...

   @mcp.tool
   def playlist_add(name: PlaylistName, url: HttpUrl, ...): ...
   ```
   For `playlist_add_many`, the items are `list[dict]` today. Either tighten the item shape with a Pydantic `PlaylistAddItem` model (cleanest) or run the validator inside the tool body before delegating to the controller.

3. **At the controller surface** — same validator, raised as plain `ValueError`:
   ```python
   # controller.py
   from ._urls import validate_http_url
   def play_url(self, name: str, url: str, title: str | None = None) -> dict:
       validate_http_url(url)
       ...
   ```

4. **At the playlist surface** — `PlaylistManager.add` and `.add_many` in `playlists.py`:
   ```python
   def add(self, name: str, url: str, title: Optional[str] = None) -> Playlist:
       ...
       url = url.strip()
       if not url:
           raise PlaylistError("url is empty")
       validate_http_url(url)
       ...
   def add_many(self, name: str, items: list[dict]) -> Playlist:
       ...
       url = str(raw["url"]).strip()
       if not url:
           raise PlaylistError(f"items[{i}] has empty url")
       validate_http_url(url)
       ...
   ```
   In playlists, wrap the `validate_http_url` call in a `try` to convert `ValueError` → `PlaylistError` for consistent error types within the playlist module — or accept `ValueError` is fine. Match the surrounding style.

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
