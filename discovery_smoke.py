"""Smoke test for zero-config speaker discovery (Flight 1, Leg 1).

Drives the real MCP tool surface via an in-process FastMCP `Client` — same
code path the agent uses, no stdio in the middle. This is the one
sanctioned hardware-touching check for the discovery pipeline itself
(discovery calls only — no audio, no group/volume changes); the pipeline's
stage logic (seeds/scan/SSDP order, NoSpeakersFound diagnostics, cache
invalidation) is otherwise covered hardware-free by tests/test_discovery.py.
Leg 02's behavior test is the full hardware acceptance check for this flight.

Sets NO env var defaults — unlike the other smoke scripts, this one is
meant to observe whatever SONOS_IPS / SONOS_SCAN_NETWORKS / HOST_IP the
shell already has (including none at all: the zero-config case this flight
exists for).

Usage:
    .venv/bin/python discovery_smoke.py                # 3x list_speakers + 1x refresh_speakers
    .venv/bin/python discovery_smoke.py --runs 1
    SONOS_SCAN_NETWORKS=192.168.86.0/24 .venv/bin/python discovery_smoke.py

Prints one JSON line per call:
    {"call": "...", "elapsed_s": <float>, "speakers": [{"name": ..., "ip": ...}, ...]}

On a tool error, prints the error text to stderr and exits non-zero.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from fastmcp import Client

from mcp_sonos.controller import SonosController
from mcp_sonos.server import mcp, register_tools


def _speaker_summary(data) -> list[dict]:
    if not isinstance(data, list):
        return []
    return [{"name": d.get("name"), "ip": d.get("ip")} for d in data]


async def _timed_call(client: Client, tool_name: str) -> dict:
    t0 = time.monotonic()
    try:
        result = await client.call_tool(tool_name)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    elapsed = time.monotonic() - t0
    data = result.data if hasattr(result, "data") else result
    return {
        "call": tool_name,
        "elapsed_s": round(elapsed, 3),
        "speakers": _speaker_summary(data),
    }


async def main(runs: int) -> None:
    controller = SonosController()
    register_tools(mcp, controller)
    async with Client(mcp) as client:
        for _ in range(runs):
            print(json.dumps(await _timed_call(client, "list_speakers")))
        print(json.dumps(await _timed_call(client, "refresh_speakers")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Smoke test for zero-config Sonos speaker discovery."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of list_speakers calls before the single refresh_speakers call (default 3).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.runs))
