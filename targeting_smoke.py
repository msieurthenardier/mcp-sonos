"""Behavior-test apparatus for target-set playback verification (flight 2).

A root-level CLI, not a pytest module: each subcommand is one shell
invocation, so a behavior test can drive it step by step and observe each
result independently. Same in-process FastMCP `Client` + `register_tools`
pattern as the other `*_smoke.py` scripts for the two subcommands that go
through an MCP tool (`stream`, `say`); every other subcommand reads/writes
SoCo directly via the shared `SonosController`, because `save-state` /
`restore-state` / `group` / `topology` / `mute-all` / `stop-all` need raw
group-membership and volume/mute control that isn't (and shouldn't be)
exposed as agent-facing MCP tools.

`group` and `restore-state` deliberately do NOT call the MCP `group` tool.
That tool can `join()` a speaker that still coordinates other members, which
flight 2's hardware probe showed is unreliable (squawk 0006). Instead both
unjoin every speaker they touch first (so every subsequent `join()` targets
an already-standalone speaker — the executor invariant `targeting.py` and
`controller.py` enforce), then join each member to its intended coordinator.

Every subcommand prints exactly one JSON document to stdout (the tool
result, or the direct-SoCo read/write it performed) and exits 0. On error,
it prints the error text to stderr and exits non-zero. No environment
defaults are set here — SONOS_IPS etc. must already be exported by the
caller if this host's zero-config discovery can't reach the household.

Subcommands:
  save-state FILE                         groups + per-speaker volume/mute -> FILE
  restore-state FILE                      restore from FILE; live re-read match report
  mute-all                                mute every visible speaker
  topology                                each group's coordinator/members/state/uri
  group COORD [MEMBERS...]                unjoin named speakers, then join MEMBERS to COORD
  stream --speakers A [B...] [--no-detach] [--url URL]   calls play_stream
  say --speakers A [B...] --text TEXT     calls say (pass-through; no "all" special-casing)
  stop-all                                stop every group's coordinator
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from fastmcp import Client

from mcp_sonos.controller import SonosController, _coordinator_of, _group_members_of
from mcp_sonos.server import mcp, register_tools

DEFAULT_STREAM_URL = "http://ice1.somafm.com/groovesalad-128-mp3"

controller = SonosController()
register_tools(mcp, controller)


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _speakers_by_name() -> dict[str, "SoCo"]:
    return {s.player_name: s for s in controller._speakers_fresh()}


# ---------------------------------------------------------------------------
# Direct-SoCo subcommands
# ---------------------------------------------------------------------------


def cmd_save_state(path: str) -> None:
    speakers = controller._speakers_fresh()
    groups: dict[str, dict] = {}
    per_speaker: dict[str, dict] = {}
    for s in speakers:
        coord = _coordinator_of(s)
        groups.setdefault(coord.uid, {"coordinator": coord.player_name, "members": []})
        groups[coord.uid]["members"].append(s.player_name)
        per_speaker[s.player_name] = {"volume": s.volume, "muted": s.mute}
    for g in groups.values():
        g["members"].sort()
    data = {"groups": sorted(groups.values(), key=lambda g: g["coordinator"]), "speakers": per_speaker}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    _emit(data)


def cmd_restore_state(path: str) -> None:
    with open(path) as f:
        data = json.load(f)

    by_name = _speakers_by_name()

    # 1. Unjoin every speaker — everyone starts standalone.
    for s in by_name.values():
        try:
            s.unjoin()
        except Exception:
            pass
    time.sleep(0.5)

    # 2. For each saved group of two or more, join each member to its
    # coordinator. Every join targets an already-standalone speaker
    # (step 1), which is the reliable case per the hardware probe.
    for g in data["groups"]:
        members = g["members"]
        if len(members) < 2:
            continue  # saved single-speaker "groups" stay standalone
        coord_name = g["coordinator"]
        coord = by_name.get(coord_name)
        if coord is None:
            continue
        for m_name in members:
            if m_name == coord_name:
                continue
            m = by_name.get(m_name)
            if m is None:
                continue
            m.join(coord)
    time.sleep(0.5)

    # 3. Restore volume + mute.
    for name, state in data["speakers"].items():
        s = by_name.get(name)
        if s is None:
            continue
        try:
            s.volume = state["volume"]
            s.mute = state["muted"]
        except Exception:
            pass
    time.sleep(0.3)

    # 4. Live re-read match report — never an echo of the file.
    controller._clear_socos_zgs_cache(list(by_name.values()))
    expected_group_of: dict[str, list[str]] = {}
    for g in data["groups"]:
        for name in g["members"]:
            expected_group_of[name] = sorted(g["members"])

    report = []
    for name, state in data["speakers"].items():
        s = by_name.get(name)
        if s is None:
            report.append({"speaker": name, "matched": False, "reason": "not found"})
            continue
        coord = _coordinator_of(s)
        actual_members = sorted(_group_members_of(coord))
        expected_members = expected_group_of.get(name, [name])
        matched = (
            s.volume == state["volume"]
            and s.mute == state["muted"]
            and actual_members == expected_members
        )
        report.append(
            {
                "speaker": name,
                "matched": matched,
                "volume": s.volume,
                "expected_volume": state["volume"],
                "muted": s.mute,
                "expected_muted": state["muted"],
                "coordinator": coord.player_name,
                "group_members": actual_members,
                "expected_group_members": expected_members,
            }
        )
    _emit({"restored_from": path, "report": report})


def cmd_mute_all() -> None:
    speakers = controller._speakers_fresh()
    for s in speakers:
        s.mute = True
    _emit({"muted": [s.player_name for s in speakers]})


def cmd_topology() -> None:
    speakers = controller._speakers_fresh()
    controller._clear_socos_zgs_cache(speakers)
    groups: dict[str, dict] = {}
    for s in speakers:
        coord = _coordinator_of(s)
        if coord.uid not in groups:
            try:
                state = coord.get_current_transport_info().get("current_transport_state")
            except Exception:
                state = None
            try:
                uri = coord.get_current_track_info().get("uri")
            except Exception:
                uri = None
            groups[coord.uid] = {"coordinator": coord.player_name, "members": [], "state": state, "uri": uri}
        groups[coord.uid]["members"].append(s.player_name)
    for g in groups.values():
        g["members"].sort()
    _emit(sorted(groups.values(), key=lambda g: g["coordinator"]))


def cmd_group(coordinator: str, members: list[str]) -> None:
    by_name = _speakers_by_name()
    names = [coordinator, *members]
    resolved = {}
    for n in names:
        s = by_name.get(n)
        if s is None:
            raise RuntimeError(f"Unknown speaker: {n!r}. Known: {sorted(by_name)}")
        resolved[n] = s

    # Never call the MCP `group` tool here (squawk 0006) — unjoin every
    # named speaker first so every join below targets an already-standalone
    # speaker.
    for n in names:
        try:
            resolved[n].unjoin()
        except Exception:
            pass
    time.sleep(0.3)

    coord = resolved[coordinator]
    for m in members:
        resolved[m].join(coord)
    time.sleep(0.3)

    controller._clear_socos_zgs_cache(list(resolved.values()))
    _emit({"coordinator": coord.player_name, "group_members": sorted(_group_members_of(coord))})


def cmd_stop_all() -> None:
    speakers = controller._speakers_fresh()
    seen: set[str] = set()
    stopped = []
    for s in speakers:
        coord = _coordinator_of(s)
        if coord.uid in seen:
            continue
        seen.add(coord.uid)
        try:
            coord.stop()
            stopped.append(coord.player_name)
        except Exception:
            pass
    _emit({"stopped": stopped})


# ---------------------------------------------------------------------------
# MCP-tool subcommands
# ---------------------------------------------------------------------------


async def cmd_stream(speaker_names: list[str], url: str, detach: bool) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "play_stream", {"speakers": speaker_names, "url": url, "detach": detach}
        )
        _emit(result.data if hasattr(result, "data") else result)


async def cmd_say(speaker_names: list[str], text: str) -> None:
    async with Client(mcp) as client:
        # Passed through UNCHANGED — no "all" special-casing here. `["all"]`
        # goes to say()'s broadcast path; `["all", "Kitchen"]` is rejected by
        # the tool's own validation, exactly like any other caller.
        result = await client.call_tool("say", {"speakers": speaker_names, "text": text})
        _emit(result.data if hasattr(result, "data") else result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Behavior-test apparatus for target-set playback (flight 2)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("save-state", help="Save groups + per-speaker volume/mute to FILE.")
    p.add_argument("file")

    p = sub.add_parser("restore-state", help="Restore groups + volume/mute from FILE; prints a live match report.")
    p.add_argument("file")

    sub.add_parser("mute-all", help="Mute every visible speaker.")

    sub.add_parser("topology", help="Print each group's coordinator, members, state, and uri.")

    p = sub.add_parser(
        "group", help="Unjoin named speakers, then join each MEMBER to COORD (never uses the MCP group tool)."
    )
    p.add_argument("coordinator")
    p.add_argument("members", nargs="*")

    p = sub.add_parser("stream", help="Call play_stream on a target set.")
    p.add_argument("--speakers", nargs="+", required=True)
    p.add_argument("--no-detach", action="store_true", help="Pass detach=false.")
    p.add_argument("--url", default=DEFAULT_STREAM_URL)

    p = sub.add_parser("say", help="Call say on a target set (or ['all']); speakers are passed through unchanged.")
    p.add_argument("--speakers", nargs="+", required=True)
    p.add_argument("--text", required=True)

    sub.add_parser("stop-all", help="Stop every group's coordinator.")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "save-state":
            cmd_save_state(args.file)
        elif args.command == "restore-state":
            cmd_restore_state(args.file)
        elif args.command == "mute-all":
            cmd_mute_all()
        elif args.command == "topology":
            cmd_topology()
        elif args.command == "group":
            cmd_group(args.coordinator, args.members)
        elif args.command == "stream":
            asyncio.run(cmd_stream(args.speakers, args.url, detach=not args.no_detach))
        elif args.command == "say":
            asyncio.run(cmd_say(args.speakers, args.text))
        elif args.command == "stop-all":
            cmd_stop_all()
    except SystemExit:
        raise
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
