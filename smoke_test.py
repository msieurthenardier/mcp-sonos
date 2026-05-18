"""In-process smoke test of the FastMCP Sonos server.

Drives the server via the real MCP protocol (FastMCP `Client` against
the `FastMCP` instance) — same code path the agent will use, just no
stdio in the middle.
"""

from __future__ import annotations

import asyncio
import json
import os

# SSDP discovery can race when not all speakers are in the discovery window.
# Set deterministic IPs by default; users with different LANs can override
# by setting SONOS_IPS in the shell before running the script.
# See CLAUDE.md "Operating constraints" for the SONOS_IPS convention.
os.environ.setdefault("SONOS_IPS", "192.168.1.51,192.168.1.52,192.168.1.53,192.168.1.54,192.168.1.55")

from fastmcp import Client

from mcp_sonos.server import mcp


def pp(label: str, result) -> None:
    """Print tool result. fastmcp returns CallToolResult."""
    data = result.data if hasattr(result, "data") else result
    print(f"\n== {label} ==")
    print(json.dumps(data, indent=2, default=str))


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print(f"Server exposes {len(tools)} tools:")
        for t in tools:
            print(f"  - {t.name}: {(t.description or '').splitlines()[0]}")

        pp("list_speakers", await client.call_tool("list_speakers"))
        pp("list_groups", await client.call_tool("list_groups"))

        # TTS on one speaker — proves single-speaker tool path end-to-end.
        pp(
            "say(Kitchen)",
            await client.call_tool(
                "say",
                {"target": "Kitchen", "text": "MCP server online. Kitchen check.", "volume": 40},
            ),
        )

        # Synced TTS across all speakers — proves grouping + sync path.
        pp(
            "say(all)",
            await client.call_tool(
                "say",
                {
                    "target": "all",
                    "text": "All speakers reporting in via the new MCP server.",
                    "volume": 40,
                },
            ),
        )

        pp(
            "now_playing(Kitchen)",
            await client.call_tool("now_playing", {"speaker": "Kitchen"}),
        )


if __name__ == "__main__":
    asyncio.run(main())
