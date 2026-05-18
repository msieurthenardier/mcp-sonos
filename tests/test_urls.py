"""Unit tests for `mcp_sonos._urls.validate_http_url`.

`validate_http_url` is the single source of truth for the HTTP(S) scheme
allow-list (per `_urls.py` docstring). It's imported at three sites
(`server.py` via Pydantic `AfterValidator`, `controller.py`, `playlists.py`),
so pinning its behavior here covers all of them by contract.
"""

from __future__ import annotations

import pytest

from mcp_sonos._urls import validate_http_url


def test_validate_http_happy():
    assert validate_http_url("http://example.com/song.mp3") == "http://example.com/song.mp3"
    assert validate_http_url("https://example.com/x.mp3") == "https://example.com/x.mp3"
    # Scheme comparison is case-insensitive — uppercase scheme survives unchanged.
    assert validate_http_url("HTTP://Example.com/x") == "HTTP://Example.com/x"


def test_validate_http_bad_scheme():
    with pytest.raises(ValueError, match="must be http or https"):
        validate_http_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="must be http or https"):
        validate_http_url("gopher://example.com/")


def test_validate_http_no_netloc():
    with pytest.raises(ValueError, match="must include a host"):
        validate_http_url("http:")
    # Empty string parses to no scheme → falls through to the bad-scheme
    # branch first; the precise message is not pinned here, only that it
    # raises ValueError.
    with pytest.raises(ValueError):
        validate_http_url("")
