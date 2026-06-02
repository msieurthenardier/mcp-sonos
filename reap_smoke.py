"""Reap-survival smoke test for the native-queue control surface.

Two-phase design — one process cannot reap itself:

  --load    Create an all-external playlist, start it via playlist_play
            (asserts engine == "native_queue"), print the result, then EXIT
            WITHOUT cleanup. The process exit is the reap. Sonos keeps playing.

  --control Run in a fresh process AFTER --load has exited (and been "reaped").
            Calls playlist_status (asserts engine == "native_queue" and live
            state present), then playlist_next, playlist_status again, and
            playlist_stop. Cleans up (stop + delete playlist) at the end.

Usage (two terminals, or sequential shell commands):

    .venv/bin/python reap_smoke.py --load
    # Wait a moment for the queue to be playing on the speaker...
    .venv/bin/python reap_smoke.py --control

See CLAUDE.md "Commands" section and the reap-resilient-control flight artifacts.
"""

from __future__ import annotations

import argparse
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

# Playlist name used across both phases.
PLAYLIST_NAME = "reap-smoke"

# Speaker name to use. Override via SONOS_SPEAKER env var.
SPEAKER = os.environ.get("SONOS_SPEAKER", "Kitchen")

# All-external SoundHelix tracks — same placeholder hostnames used by
# queue_smoke.py; these URLs survive MCP restarts because they are
# served by SoundHelix, not by the in-process audio server.
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


def pp(label: str, result) -> None:
    data = result.data if hasattr(result, "data") else result
    print(f"\n== {label} ==")
    print(json.dumps(data, indent=2, default=str))


def _fail(msg: str) -> None:
    print(f"\nFAIL: {msg}", file=sys.stderr)
    sys.exit(1)


async def phase_load(client: Client) -> None:
    """Create an all-external playlist, start it, then EXIT (= the reap)."""
    print(f"[--load] Checking speakers are reachable on {SPEAKER!r}...")

    # Quick reachability check: list_speakers.  Fail fast if nothing found.
    speakers = await client.call_tool("list_speakers", {})
    speaker_data = speakers.data if hasattr(speakers, "data") else speakers
    if not speaker_data:
        _fail(
            "No speakers found. Is SONOS_IPS set correctly? "
            "Is the Sonos household on the same LAN?"
        )
    print(f"  Found {len(speaker_data)} speaker(s).")

    # Idempotent setup: delete any leftover playlist from a prior run.
    try:
        await client.call_tool("playlist_delete", {"name": PLAYLIST_NAME})
        print(f"  Deleted leftover playlist {PLAYLIST_NAME!r}.")
    except Exception:
        pass

    # Create the playlist and populate it with all-external URLs.
    await client.call_tool("playlist_create", {"name": PLAYLIST_NAME})
    await client.call_tool(
        "playlist_add_many",
        {"name": PLAYLIST_NAME, "items": EXTERNAL_TRACKS},
    )
    print(f"  Created playlist {PLAYLIST_NAME!r} with {len(EXTERNAL_TRACKS)} tracks.")

    # Start playback.
    result = await client.call_tool(
        "playlist_play",
        {"speaker": SPEAKER, "name": PLAYLIST_NAME},
    )
    pp("playlist_play", result)

    data = result.data if hasattr(result, "data") else result
    if data.get("engine") != "native_queue":
        _fail(
            f"Expected engine='native_queue' but got {data.get('engine')!r}. "
            "Ensure all track URLs are external (not MCP-hosted)."
        )

    print(
        "\n[--load] Queue loaded and playing. Engine = native_queue. "
        "Process exiting now (this is the reap). "
        "The Sonos hardware will keep playing."
    )
    # EXIT without cleanup — the process exit is the reap.
    # Do NOT call playlist_stop or playlist_delete here.


async def phase_control(client: Client) -> None:
    """In a fresh process, drive the live queue and then clean up."""
    print(f"[--control] Checking speakers are reachable on {SPEAKER!r}...")

    # Quick reachability check.
    speakers = await client.call_tool("list_speakers", {})
    speaker_data = speakers.data if hasattr(speakers, "data") else speakers
    if not speaker_data:
        _fail(
            "No speakers found. Is SONOS_IPS set correctly? "
            "Is the Sonos household on the same LAN?"
        )
    print(f"  Found {len(speaker_data)} speaker(s).")

    # Step 1: playlist_status — must show engine=native_queue and live state.
    result = await client.call_tool("playlist_status", {"speaker": SPEAKER})
    pp("playlist_status (initial)", result)
    data = result.data if hasattr(result, "data") else result

    if data.get("engine") != "native_queue":
        _fail(
            f"Expected engine='native_queue' but got {data.get('engine')!r}. "
            "Did --load succeed and is the queue still playing?"
        )
    if not data.get("state") and not data.get("uri") and not data.get("playlist_position"):
        _fail(
            "playlist_status returned no live state. "
            "Is the queue still playing? Did --load run first?"
        )
    print("  engine=native_queue confirmed. Live state present.")

    # Step 2: advance to the next track.
    result = await client.call_tool("playlist_next", {"speaker": SPEAKER})
    pp("playlist_next", result)

    # Step 3: status after advance.
    result = await client.call_tool("playlist_status", {"speaker": SPEAKER})
    pp("playlist_status (after next)", result)

    # Step 4: stop playback.
    result = await client.call_tool("playlist_stop", {"speaker": SPEAKER})
    pp("playlist_stop", result)

    # Cleanup: delete the playlist.
    try:
        await client.call_tool("playlist_delete", {"name": PLAYLIST_NAME})
        print(f"\n  Cleaned up: playlist {PLAYLIST_NAME!r} deleted.")
    except Exception as exc:
        print(f"\n  Note: could not delete playlist {PLAYLIST_NAME!r}: {exc}")

    print("\n[--control] Done. Reap-survival smoke PASSED.")


async def main(phase: str) -> None:
    async with Client(mcp) as client:
        if phase == "load":
            await phase_load(client)
        else:
            await phase_control(client)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reap-survival smoke test for mcp-sonos native-queue control."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--load",
        action="store_const",
        const="load",
        dest="phase",
        help=(
            "Load an all-external playlist and start it via playlist_play, "
            "assert engine=native_queue, then EXIT (the process exit is the reap)."
        ),
    )
    group.add_argument(
        "--control",
        action="store_const",
        const="control",
        dest="phase",
        help=(
            "In a fresh process: drive the live queue with playlist_status, "
            "playlist_next, playlist_status, playlist_stop; assert engine=native_queue; "
            "then clean up (stop + delete playlist)."
        ),
    )
    args = parser.parse_args()
    asyncio.run(main(args.phase))
