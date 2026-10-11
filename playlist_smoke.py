"""Smoke test for playlist continuous playback.

Run with no arguments for the three legacy sub-tests below, or with the
single argument `dj` to run only the DJ voice-segment scenario (see
`test_dj`): `python playlist_smoke.py dj`. The dj scenario targets
SMOKE_SPEAKER (default "Kitchen") and, if SMOKE_VOLUME is set, applies it
for the run and restores the prior volume afterwards.

Three legacy sub-tests run sequentially:
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
import sys
import time

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

from mcp_sonos.controller import SonosController
from mcp_sonos.server import mcp, register_tools
from mcp_sonos.tts import synthesize

from _smoke_common import select_track_pool

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
        "playlist_play", {"speakers": ["Kitchen"], "name": "smoke"}))
    for i in range(7):
        await asyncio.sleep(2.0)
        s = await status(client)
        print(f"  t+{(i+1)*2:>2}s  running={s.get('running')} "
              f"idx={s.get('current_index')} "
              f"item={(s.get('current_item') or {}).get('title')}")


async def test_skip(client: Client) -> None:
    print("\n\n###### Test 2: skip mid-track ######")
    await build_playlist(client)
    await client.call_tool("playlist_play", {"speakers": ["Kitchen"], "name": "smoke"})
    await asyncio.sleep(1.5)  # let track 1 start
    pp("status before skip", await status(client))
    pp("skip", await client.call_tool("playlist_next", {"speaker": "Kitchen"}))
    await asyncio.sleep(2.0)
    pp("status after skip", await status(client))
    pp("stop", await client.call_tool("playlist_stop", {"speaker": "Kitchen"}))


async def test_stop(client: Client) -> None:
    print("\n\n###### Test 3: stop mid-track ######")
    await build_playlist(client)
    await client.call_tool("playlist_play", {"speakers": ["Kitchen"], "name": "smoke"})
    await asyncio.sleep(1.5)
    pp("status before stop", await status(client))
    pp("stop", await client.call_tool("playlist_stop", {"speaker": "Kitchen"}))
    await asyncio.sleep(1.0)
    pp("status after stop", await status(client))


class SmokeFailure(Exception):
    """A dj-scenario assertion failed or timed out."""


async def _poll_status(client: Client, speaker: str) -> dict:
    r = await client.call_tool("playlist_status", {"speaker": speaker})
    return r.data if hasattr(r, "data") else r


async def _wait_current(client, speaker, pred, what, *, timeout, observe_playing=False):
    """Poll playlist_status until `pred(current_item, status)` holds. With
    `observe_playing`, also require that now_playing showed PLAYING with
    uri == the item's hosted url at some point while it was current."""
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        st = await _poll_status(client, speaker)
        last = st
        item = st.get("current_item") or {}
        if pred(item, st):
            if not observe_playing:
                return item
            np = await client.call_tool("now_playing", {"speaker": speaker})
            np = np.data if hasattr(np, "data") else np
            if np.get("state") == "PLAYING" and np.get("uri") == item.get("url"):
                return item
        await asyncio.sleep(0.2)
    raise SmokeFailure(f"timed out ({timeout}s) waiting for: {what}; last status: {last}")


async def test_dj(client: Client, speaker: str) -> None:
    print("\n\n###### DJ test: track -> voice -> track, then live-appended voice ######")
    pool = select_track_pool()
    name = "smoke-dj"
    try:
        await client.call_tool("playlist_delete", {"name": name})
    except Exception:
        pass
    await client.call_tool("playlist_create", {"name": name})
    try:
        res = await client.call_tool("playlist_add_many", {"name": name, "items": [
            {"url": pool[0]["url"], "title": pool[0]["title"]},
            {"text": "That was the first track. Up next, another one."},
            {"url": pool[1]["url"], "title": pool[1]["title"]},
        ]})
        built = (res.data if hasattr(res, "data") else res)["items"]
        if [i["kind"] for i in built] != ["track", "voice", "track"]:
            raise SmokeFailure(f"unexpected built kinds: {built}")

        play = await client.call_tool("playlist_play", {"speakers": [speaker], "name": name})
        play = play.data if hasattr(play, "data") else play
        pp("play", play)
        if play.get("engine") != "worker":
            raise SmokeFailure(f"mixed playlist should use the worker engine, got {play.get('engine')}")

        await _wait_current(client, speaker, lambda i, s: i.get("kind") == "track",
                            "first track current", timeout=30)
        await asyncio.sleep(2.0)  # let the song actually start
        await client.call_tool("playlist_next", {"speaker": speaker})  # skip past the long part
        voice = await _wait_current(
            client, speaker, lambda i, s: i.get("kind") == "voice" and i.get("text"),
            "voice item current AND now_playing PLAYING its hosted url",
            timeout=45, observe_playing=True)
        print(f"  voice item observed playing: {voice.get('title')!r}")

        nxt = await _wait_current(client, speaker, lambda i, s: i.get("kind") == "track"
                                  and i.get("url") == pool[1]["url"],
                                  "advance to the next track", timeout=45)
        print(f"  advanced to: {nxt.get('title')!r}")

        # Live append while the last item plays.
        await client.call_tool("playlist_add", {"name": name, "text": "And that was the last track. Goodnight."})
        await asyncio.sleep(1.0)
        await client.call_tool("playlist_next", {"speaker": speaker})
        tail = await _wait_current(
            client, speaker, lambda i, s: i.get("kind") == "voice" and "Goodnight" in (i.get("text") or ""),
            "live-appended voice item current AND PLAYING", timeout=45, observe_playing=True)
        print(f"  appended voice item observed: {tail.get('title')!r}")
    finally:
        try:
            await client.call_tool("playlist_stop", {"speaker": speaker})
        except Exception:
            pass
        try:
            await client.call_tool("playlist_delete", {"name": name})
        except Exception:
            pass


async def main_dj() -> int:
    speaker = os.environ.get("SMOKE_SPEAKER", "Kitchen")
    vol_env = os.environ.get("SMOKE_VOLUME")
    prior = None
    rc = 0
    try:
        if vol_env:
            prior = controller._resolve(speaker).volume
            controller.set_volume(speaker, int(vol_env))
        async with Client(mcp) as client:
            await test_dj(client, speaker)
        print("\nDJ smoke: PASS")
    except SmokeFailure as e:
        print(f"\nDJ smoke: FAIL - {e}", file=sys.stderr)
        rc = 1
    except Exception as e:  # any tool/transport error is a failure too
        print(f"\nDJ smoke: FAIL - unexpected {type(e).__name__}: {e}", file=sys.stderr)
        rc = 1
    finally:
        if prior is not None:
            try:
                controller.set_volume(speaker, prior)
            except Exception as e:
                print(f"WARNING: could not restore volume {prior}: {e}", file=sys.stderr)
    return rc


async def main() -> None:
    async with Client(mcp) as client:
        await test_natural_end(client)
        await test_skip(client)
        await test_stop(client)
        await client.call_tool("playlist_delete", {"name": "smoke"})
        print("\nDone.")


if __name__ == "__main__":
    if sys.argv[1:] == ["dj"]:
        sys.exit(asyncio.run(main_dj()))
    elif len(sys.argv) > 1:
        sys.exit(f"usage: {sys.argv[0]} [dj]")
    asyncio.run(main())
