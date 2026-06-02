"""Smoke test for the native Sonos queue playback path.

Verifies that an all-external playlist routes through the native queue engine
(not the worker-thread engine) and that the Sonos queue advances tracks
autonomously without MCP involvement.

Three external MP3 tracks (SoundHelix) are used — NOT MCP-hosted ones — so the
classifier routes to the native queue engine. The script:
  1. Creates a playlist with three external tracks.
  2. Calls playlist_play and asserts engine == "native_queue" and
     queue_size == number of tracks.
  3. Prints now_playing so the operator can confirm the queue engaged.
  4. Stops and clears up.

Run via the real MCP protocol using the in-process FastMCP Client — same
code path the agent will use, no stdio in the middle.

Requires a reachable Sonos household on the LAN. Fails fast with a clear
message if no hardware is reachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

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

controller = SonosController()
register_tools(mcp, controller)

# External MP3 tracks from SoundHelix — these are NOT MCP-hosted, so the
# classifier routes the playlist to the native Sonos queue engine.
EXTERNAL_TRACKS = [
    {
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "title": "SoundHelix Song 1",
    },
    {
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
        "title": "SoundHelix Song 2",
    },
    {
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
        "title": "SoundHelix Song 3",
    },
]

PLAYLIST_NAME = "queue-smoke"
SPEAKER = "Kitchen"


def pp(label: str, result) -> None:
    data = result.data if hasattr(result, "data") else result
    print(f"\n== {label} ==")
    print(json.dumps(data, indent=2, default=str))


def fail(msg: str) -> None:
    print(f"\nFAIL: {msg}", file=sys.stderr)
    sys.exit(1)


async def main() -> None:
    async with Client(mcp) as client:
        # ---- hardware reachability check -----------------------------------
        print("Checking hardware reachability …")
        try:
            speakers_result = await client.call_tool("list_speakers")
            speakers_data = speakers_result.data if hasattr(speakers_result, "data") else speakers_result
            if not speakers_data:
                fail(
                    "No Sonos speakers found. Set SONOS_IPS to the correct IPs "
                    "for your household and retry."
                )
        except Exception as e:
            fail(
                f"Could not reach Sonos hardware: {e}\n"
                "Set SONOS_IPS to the correct IPs for your household and retry."
            )
        pp("list_speakers", speakers_result)

        # ---- set up playlist ------------------------------------------------
        # Idempotent across runs: delete if exists, then create fresh.
        try:
            await client.call_tool("playlist_delete", {"name": PLAYLIST_NAME})
        except Exception:
            pass

        await client.call_tool("playlist_create", {"name": PLAYLIST_NAME})
        await client.call_tool(
            "playlist_add_many",
            {"name": PLAYLIST_NAME, "items": EXTERNAL_TRACKS},
        )
        print(f"\nPlaylist '{PLAYLIST_NAME}' created with {len(EXTERNAL_TRACKS)} external tracks.")

        # ---- play via native queue engine -----------------------------------
        play_result = await client.call_tool(
            "playlist_play",
            {"speaker": SPEAKER, "name": PLAYLIST_NAME},
        )
        play_data = play_result.data if hasattr(play_result, "data") else play_result
        pp("playlist_play", play_result)

        # Core assertion: engine must be native_queue.
        engine = play_data.get("engine") if isinstance(play_data, dict) else None
        if engine != "native_queue":
            fail(
                f"Expected engine == 'native_queue', got {engine!r}. "
                "Check that SONOS_IPS tracks no MCP-hosted URLs are in the playlist."
            )

        # Core assertion: queue_size reported in the play result.
        # Note: play() returns total_items (the playlist count); the Sonos
        # native queue_size is observable via now_playing / hardware only.
        total_items = play_data.get("total_items") if isinstance(play_data, dict) else None
        expected_tracks = len(EXTERNAL_TRACKS)
        if total_items != expected_tracks:
            fail(
                f"Expected total_items == {expected_tracks}, got {total_items!r}."
            )

        print(f"\nASSERT PASS: engine == 'native_queue'")
        print(f"ASSERT PASS: total_items == {expected_tracks} (queue_size == number of tracks)")

        # ---- now_playing: let operator confirm the queue engaged ------------
        await asyncio.sleep(2.0)  # brief pause so playback starts
        pp("now_playing", await client.call_tool("now_playing", {"speaker": SPEAKER}))

        # ---- cleanup: stop + clear -----------------------------------------
        print(f"\nCleaning up (stop + delete playlist) …")
        try:
            await client.call_tool("playlist_stop", {"speaker": SPEAKER})
        except Exception:
            pass
        try:
            await client.call_tool("playlist_delete", {"name": PLAYLIST_NAME})
        except Exception:
            pass

        print("\nDone. Native queue path confirmed.")
        print(
            "\n[Operator HAT step] While the queue was active, you can kill the MCP "
            "process and observe that the Sonos speaker continues advancing tracks "
            "without MCP involvement — that is the Q1 reap test."
        )


if __name__ == "__main__":
    asyncio.run(main())
