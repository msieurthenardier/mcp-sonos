"""Smoke test for playlist continuous playback.

Three sub-tests run sequentially:
  1. Natural-end: build a 3-item playlist, play it through, watch
     index advance via status, confirm worker exits naturally.
  2. Skip: start fresh, skip the first item early, confirm advance.
  3. Stop: start fresh, stop mid-track, confirm session ends.

All through the real MCP protocol via the in-process FastMCP Client —
same code path the agent will use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

# SSDP discovery can race when not all speakers are in the discovery window.
# Set deterministic IPs by default; users with different LANs can override
# by setting SONOS_IPS in the shell before running the script.
# See CLAUDE.md "Operating constraints" for the SONOS_IPS convention.
os.environ.setdefault("SONOS_IPS", "192.168.1.51,192.168.1.52,192.168.1.53,192.168.1.54,192.168.1.55")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s",
)
for noisy in ("soco", "soco.services", "urllib3", "mcp", "FastMCP"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from fastmcp import Client

from mcp_sonos.controller import SonosController
from mcp_sonos.server import mcp, register_tools
from mcp_sonos.tts import synthesize

controller = SonosController()
register_tools(mcp, controller)


def pp(label: str, result) -> None:
    data = result.data if hasattr(result, "data") else result
    print(f"\n== {label} ==")
    print(json.dumps(data, indent=2, default=str))


async def build_playlist(client: Client) -> list[dict]:
    clips = []
    for i, phrase in enumerate(
        [
            "Track one. First track in the playlist.",
            "Track two. Continuous playback is working.",
            "Track three. End of the playlist.",
        ],
        start=1,
    ):
        path = synthesize(phrase, controller.cache_dir)
        url = controller.audio.url_for(path.name)
        clips.append({"url": url, "title": f"Track {i}"})
    # Idempotent across runs: delete if exists, then create fresh.
    try:
        await client.call_tool("playlist_delete", {"name": "smoke"})
    except Exception:
        pass
    await client.call_tool("playlist_create", {"name": "smoke"})
    await client.call_tool("playlist_add_many", {"name": "smoke", "items": clips})
    return clips


async def status(client: Client) -> dict:
    r = await client.call_tool("playlist_status", {"speaker": "Kitchen"})
    return r.data if hasattr(r, "data") else r


async def test_natural_end(client: Client) -> None:
    print("\n\n###### Test 1: natural end across 3 tracks ######")
    await build_playlist(client)
    pp("play", await client.call_tool(
        "playlist_play", {"speaker": "Kitchen", "name": "smoke"}))
    for i in range(7):
        await asyncio.sleep(2.0)
        s = await status(client)
        print(f"  t+{(i+1)*2:>2}s  running={s.get('running')} "
              f"idx={s.get('current_index')} "
              f"item={(s.get('current_item') or {}).get('title')}")


async def test_skip(client: Client) -> None:
    print("\n\n###### Test 2: skip mid-track ######")
    await build_playlist(client)
    await client.call_tool("playlist_play", {"speaker": "Kitchen", "name": "smoke"})
    await asyncio.sleep(1.5)  # let track 1 start
    pp("status before skip", await status(client))
    pp("skip", await client.call_tool("playlist_next", {"speaker": "Kitchen"}))
    await asyncio.sleep(2.0)
    pp("status after skip", await status(client))
    pp("stop", await client.call_tool("playlist_stop", {"speaker": "Kitchen"}))


async def test_stop(client: Client) -> None:
    print("\n\n###### Test 3: stop mid-track ######")
    await build_playlist(client)
    await client.call_tool("playlist_play", {"speaker": "Kitchen", "name": "smoke"})
    await asyncio.sleep(1.5)
    pp("status before stop", await status(client))
    pp("stop", await client.call_tool("playlist_stop", {"speaker": "Kitchen"}))
    await asyncio.sleep(1.0)
    pp("status after stop", await status(client))


async def main() -> None:
    async with Client(mcp) as client:
        await test_natural_end(client)
        await test_skip(client)
        await test_stop(client)
        await client.call_tool("playlist_delete", {"name": "smoke"})
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
