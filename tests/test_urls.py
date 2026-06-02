"""Unit tests for `mcp_sonos._urls`.

Covers:
- ``validate_http_url`` — the HTTP(S) scheme allow-list used at three sites.
- ``is_mcp_hosted`` — host/port-relative classifier for MCP in-process audio
  URLs; hardware-free (synthetic host/port).
"""

from __future__ import annotations

import pytest

from mcp_sonos._urls import is_mcp_hosted, validate_http_url


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


# ---------------------------------------------------------------------------
# is_mcp_hosted
# ---------------------------------------------------------------------------

_HOST = "192.168.1.50"
_PORT = 8080


def test_is_mcp_hosted_same_host_and_port_returns_true():
    """AC: same host+port → True (canonical case)."""
    assert is_mcp_hosted(f"http://{_HOST}:{_PORT}/tts/abc123.wav", _HOST, _PORT) is True


def test_is_mcp_hosted_genuine_mcp_url_returns_true():
    """AC: a genuine MCP audio-host URL → True."""
    assert is_mcp_hosted(f"http://{_HOST}:{_PORT}/file.mp3", _HOST, _PORT) is True


def test_is_mcp_hosted_bare_base_url_returns_true():
    """AC: bare base URL with no path → True (acceptable)."""
    assert is_mcp_hosted(f"http://{_HOST}:{_PORT}", _HOST, _PORT) is True


def test_is_mcp_hosted_different_host_returns_false():
    """AC: external URL on a different host → False."""
    assert is_mcp_hosted("http://192.168.1.99:8080/song.mp3", _HOST, _PORT) is False


def test_is_mcp_hosted_no_explicit_port_returns_false():
    """AC: URL with no explicit port → False (parsed.port is None)."""
    assert is_mcp_hosted("https://blog.example/a.mp3", _HOST, _PORT) is False


def test_is_mcp_hosted_same_host_no_port_returns_false():
    """AC: same host but no explicit port → False."""
    assert is_mcp_hosted(f"http://{_HOST}/file.mp3", _HOST, _PORT) is False


def test_is_mcp_hosted_same_host_different_port_returns_false():
    """AC: same host but a different port → False."""
    assert is_mcp_hosted(f"http://{_HOST}:9090/file.mp3", _HOST, _PORT) is False


def test_is_mcp_hosted_malformed_noninteger_port_returns_false():
    """AC: non-integer port token makes urlparse.port raise → swallowed, returns False."""
    assert is_mcp_hosted(f"http://{_HOST}:notaport/x", _HOST, _PORT) is False


def test_is_mcp_hosted_empty_string_returns_false():
    """Malformed input edge: empty string → False, no raise."""
    assert is_mcp_hosted("", _HOST, _PORT) is False


def test_is_mcp_hosted_completely_malformed_returns_false():
    """Malformed input edge: garbage string → False, no raise."""
    assert is_mcp_hosted("not a url at all", _HOST, _PORT) is False
