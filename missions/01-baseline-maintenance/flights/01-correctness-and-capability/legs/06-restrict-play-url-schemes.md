# Leg: 06-restrict-play-url-schemes

**Status**: completed
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
- [x] `play_url("Kitchen", "file:///etc/passwd")` returns a validation error at the MCP tool surface
- [x] `play_url("Kitchen", "gopher://example.com/")` returns a validation error at the MCP tool surface
- [x] `play_url("Kitchen", "http://example.com/song.mp3")` and `play_url("Kitchen", "https://example.com/song.mp3")` still work
- [x] **Defence-in-depth — bypassing the MCP layer also rejects**: calling `controller.play_url("Kitchen", "file://...")` directly raises `ValueError`
- [x] **Defence-in-depth — playlist module**: `controller.playlists.add("p", "file://...")` and `.add_many("p", [{"url":"file://..."}])` both raise `PlaylistError`
- [x] `playlist_add_many` mixed-validity: `items=[{"url":"http://ok"},{"url":"file:///bad"}]` fails the whole call with an `items[1]` error and does NOT partially append (matches existing per-index fail-fast semantics)
- [x] URLs without a netloc (e.g. `"http:"`, `"https:"`) are also rejected — scheme alone is insufficient
- [x] No regression in playlist smoke tests

## Verification Steps
- Manual: call `play_url` with a `file://` URL via an MCP client; observe the validation error in the MCP response.
- Manual: call with a valid `http://...mp3` URL; observe success.
- `playlist_smoke.py` passes against live hardware.

## Implementation Guidance

**Defence in depth**: validate at *both* the tool surface (clean MCP error for agents) AND the controller/playlist surface (catches non-MCP callers — future test scaffolding in Flight 4, automation scripts, anything that imports the controller directly). Same validator function reused at all three sites.

1. **Create the validator** in a new module `mcp_sonos/_urls.py` (committed decision — inline in `controller.py` would require cross-module imports from `playlists.py` and `server.py`):
   ```python
   from urllib.parse import urlparse
   _ALLOWED_SCHEMES = {"http", "https"}
   def validate_http_url(u: str) -> str:
       parsed = urlparse(u)
       scheme = parsed.scheme.lower()
       if scheme not in _ALLOWED_SCHEMES:
           raise ValueError(f"URL scheme must be http or https; got {scheme!r}")
       if not parsed.netloc:
           raise ValueError(f"URL must include a host; got {u!r}")
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
   For `playlist_add_many`: **validate inside the tool body** before delegating to the controller. Keeps `PlaylistManager.add_many` signature (`list[dict]`) stable. Tightening to a Pydantic `PlaylistAddItem` model would force a controller-signature change for a defence-in-depth fix — not worth it.
   ```python
   @mcp.tool
   def playlist_add_many(name: PlaylistName, items: list[dict]) -> dict:
       for i, raw in enumerate(items):
           if isinstance(raw, dict) and "url" in raw:
               try:
                   validate_http_url(str(raw["url"]).strip())
               except ValueError as e:
                   raise ValueError(f"items[{i}]: {e}")
       return controller.playlists.add_many(name, items).to_dict()
   ```
   The dict-shape check is loose here because `PlaylistManager.add_many` already enforces it at `playlists.py:144-149` with the same per-index error idiom — the tool-side validator just additionally checks scheme.

3. **At the controller surface** — same validator, raised as plain `ValueError`:
   ```python
   # controller.py
   from ._urls import validate_http_url
   def play_url(self, name: str, url: str, title: str | None = None) -> dict:
       validate_http_url(url)
       ...
   ```

4. **At the playlist surface** — `PlaylistManager.add` and `.add_many` in `playlists.py`. Use `PlaylistError` (subclass of `ValueError`, defined at line 86) for consistency with surrounding error style:
   ```python
   from ._urls import validate_http_url

   def add(self, name: str, url: str, title: Optional[str] = None) -> Playlist:
       ...
       url = url.strip()
       if not url:
           raise PlaylistError("url is empty")
       try:
           validate_http_url(url)
       except ValueError as e:
           raise PlaylistError(str(e))
       ...

   def add_many(self, name: str, items: list[dict]) -> Playlist:
       ...
       for i, raw in enumerate(items):
           ...
           url = str(raw["url"]).strip()
           if not url:
               raise PlaylistError(f"items[{i}] has empty url")
           try:
               validate_http_url(url)
           except ValueError as e:
               raise PlaylistError(f"items[{i}]: {e}")
           ...
   ```
   Note the `add_many` build-then-extend pattern at `playlists.py:144-153`: validation happens in the build loop, so a bad item raises before `pl.items.extend(normalized)` runs — partial append is structurally impossible. The mixed-validity AC is satisfied by this existing structure.

## Files Affected
- `mcp_sonos/server.py` — three tool definitions
- (Possibly) `mcp_sonos/playlists.py` — if there's a shared `PlaylistItem`-like model

## Edge Cases
- **Empty string**: `urlparse("").scheme` → `""`, rejected. Good.
- **URLs without scheme** (e.g., `example.com/song.mp3`): `urlparse` returns `scheme=""`, rejected with a clear error. Better than letting Sonos receive a malformed URI.
- **Mixed case scheme** (`HTTP://...`): lowercase before comparison.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Playlist smoke test passes
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
