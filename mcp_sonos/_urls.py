"""URL validation shared across the tool, controller, and playlist surfaces.

Single source of truth for the HTTP(S) scheme allow-list. Used at three
sites for defence in depth:

- `server.py` — via Pydantic `AfterValidator`, so MCP clients receive a
  clean validation error before the controller is ever called.
- `controller.py` — catches direct (non-MCP) callers.
- `playlists.py` — catches callers that bypass the controller too.

All three reuse the same `validate_http_url` function so the policy stays
in one place.
"""

from __future__ import annotations

from urllib.parse import urlparse


_ALLOWED_SCHEMES = {"http", "https"}


def validate_http_url(u: str) -> str:
    """Return `u` unchanged if it parses as an `http`/`https` URL with a host.

    Raises `ValueError` otherwise. Scheme comparison is case-insensitive.
    A scheme without a netloc (e.g. ``"http:"``) is rejected because
    Sonos cannot resolve a host-less URI and we want a clean error
    rather than a downstream UPnP failure.
    """
    parsed = urlparse(u)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"URL scheme must be http or https; got {scheme!r}")
    if not parsed.netloc:
        raise ValueError(f"URL must include a host; got {u!r}")
    return u
