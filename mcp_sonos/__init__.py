"""Sonos MCP server — local control over WiFi via UPnP/SoCo."""

__version__ = "0.4.0"

from .controller import SonosController

__all__ = ["SonosController", "__version__"]
