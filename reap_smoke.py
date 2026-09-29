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

The all-external playlist that --load builds comes from
`_smoke_common.select_track_pool()`: a primary (SoundHelix) host, with a
fallback to a different host if the primary is unreachable at load time.
See `_smoke_common.py` for the pools and probe details — in short, this
only protects against a single-host outage (not "no network at smoke
time" generally), and the reachability probe runs from this machine, not
from the speaker.

See CLAUDE.md "Commands" section and the reap-resilient-control flight artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

# Zero-config discovery (seeds -> bounded scan -> SSDP) runs with no env vars
# set. Set SONOS_IPS in the shell first if this host's default scan can't
# reach the household (see CLAUDE.md "Operating constraints").

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s",
)
for noisy in ("soco", "soco.services", "urllib3", "mcp", "FastMCP"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from fastmcp import Client

from _smoke_common import select_track_pool
from mcp_sonos.controller import SonosController
from mcp_sonos.server import mcp, register_tools

controller = SonosController()
register_tools(mcp, controller)

# Playlist name used across both phases.
PLAYLIST_NAME = "reap-smoke"

# Speaker name to use. Override via SONOS_SPEAKER env var.
SPEAKER = os.environ.get("SONOS_SPEAKER", "Kitchen")

# All-external tracks — same pool/probe helper used by queue_smoke.py (see
# _smoke_common.py). The track pool (primary SoundHelix, fallback on a
# different host if SoundHelix is unreachable) is selected only in
# phase_load(), NOT at import time: --control never needs a track list (it
# drives the already-live queue via playlist_status/next/stop), so it must
# not pay the probe's network cost or depend on re-probing landing on the
# same pool --load picked. These URLs survive MCP restarts because they are
# served externally, not by the in-process audio server.


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

    # Quick reachability check: list_speakers. Fail fast (via _fail, not a
    # crash) if discovery's seeds/scan/SSDP pipeline came up empty —
    # list_speakers raises a ToolError with the pipeline's own diagnostics
    # in that case, so this must not let the exception propagate uncaught.
    try:
        speakers = await client.call_tool("list_speakers", {})
        speaker_data = speakers.data if hasattr(speakers, "data") else speakers
    except Exception as e:
        _fail(
            f"Could not reach Sonos hardware: {e}\n"
            "list_speakers already tried seeds, a bounded subnet scan, and "
            "SSDP — see its message above for what to set (SONOS_IPS, "
            "SONOS_SCAN_NETWORKS, or HOST_IP)."
        )
    print(f"  Found {len(speaker_data)} speaker(s).")

    # Select an external track pool now (probe primary, fall back on a
    # single-host outage). Only --load needs this — see module docstring.
    print("  Probing external track hosts …")
    external_tracks = select_track_pool()
    chosen_host = external_tracks[0]["url"].split("/")[2]
    print(f"  Using track pool hosted on {chosen_host!r} ({len(external_tracks)} tracks).")

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
        {"name": PLAYLIST_NAME, "items": external_tracks},
    )
    print(f"  Created playlist {PLAYLIST_NAME!r} with {len(external_tracks)} tracks.")

    # Start playback.
    result = await client.call_tool(
        "playlist_play",
        {"speakers": [SPEAKER], "name": PLAYLIST_NAME},
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

    # Quick reachability check. Same rationale as phase_load: list_speakers
    # raises (ToolError) rather than returning empty when discovery finds
    # nothing, so this must catch it and route to _fail instead of crashing.
    try:
        speakers = await client.call_tool("list_speakers", {})
        speaker_data = speakers.data if hasattr(speakers, "data") else speakers
    except Exception as e:
        _fail(
            f"Could not reach Sonos hardware: {e}\n"
            "list_speakers already tried seeds, a bounded subnet scan, and "
            "SSDP — see its message above for what to set (SONOS_IPS, "
            "SONOS_SCAN_NETWORKS, or HOST_IP)."
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
