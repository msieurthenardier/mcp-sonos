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


def any_mcp_hosted(urls: list[str], host_ip: str, port: int) -> bool:
    """Return ``True`` iff *any* URL in *urls* is served by the MCP audio host.

    A one-liner composition over ``is_mcp_hosted`` used by ``playlist_play``
    to decide whether to fall back to the worker engine (mixed playlists
    containing TTS/staged files cannot use the native Sonos queue because the
    audio host would be unreachable after an MCP process restart).
    """
    return any(is_mcp_hosted(u, host_ip, port) for u in urls)


def is_mcp_hosted(url: str, host_ip: str, port: int) -> bool:
    """Return ``True`` iff *url* is served by the MCP in-process audio host.

    An MCP-hosted URL has the form ``http://{host_ip}:{port}/{file}``.  The
    check is exact on both host and port:

    - A URL on a different host → ``False``
    - A URL with no explicit port (e.g. ``https://blog.example/a.mp3``) → ``False``
    - A URL on the same host but a different port → ``False``

    Malformed input (including URLs with a non-integer port token, which make
    ``urlparse(...).port`` raise ``ValueError``) is caught and returns ``False``
    rather than propagating the exception.  This deliberately differs from
    ``validate_http_url``, which raises by design.
    """
    try:
        parsed = urlparse(url)
        return parsed.hostname == host_ip and parsed.port == port
    except Exception:
        return False
