"""Verify that mcp.version and mcp_sonos.__version__ agree and equal 0.6.1."""

import mcp_sonos
from mcp_sonos.server import mcp


def test_package_version() -> None:
    assert mcp_sonos.__version__ == "0.6.1"


def test_mcp_version_matches_package() -> None:
    assert mcp.version == mcp_sonos.__version__


def test_mcp_version_is_not_fastmcp_version() -> None:
    # FastMCP's own framework version (4.x); project version is 0.6.x.
    import fastmcp

    assert mcp.version != fastmcp.__version__
    assert not mcp.version.startswith(("3.", "4.")), (
        f"mcp.version looks like the FastMCP framework version, not the project version: {mcp.version!r}"
    )
