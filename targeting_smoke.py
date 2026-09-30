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

`stop-all` and `restore-state` are the two exceptions to "exits 0 or prints
to stderr": both always print their JSON report to stdout (never swallowed
into stderr), and exit non-zero if that report shows a problem (a group
still PLAYING, or a mismatch/unreadable speaker) — see their docstrings.

Subcommands:
  save-state FILE                         groups + per-speaker volume/mute -> FILE
  restore-state FILE                      restore from FILE; live re-read match report
  mute-all                                mute every visible speaker
  topology                                each group's coordinator/members/state/uri
  group COORD [MEMBERS...]                unjoin named speakers, then join MEMBERS to COORD
  stream --speakers A [B...] [--no-detach] [--url URL]   calls play_stream
  say --speakers A [B...] --text TEXT     calls say (pass-through; no "all" special-casing)
  stop-all                                stop every group's coordinator

Leg 4 (coordinator-view hardening): topology views are per-speaker and
eventually consistent, and SoCo caches whichever speaker's view it last
polled, per household, for 5s (see CLAUDE.md's grouping invariant). Every
read in this apparatus that a caller might act on now goes through
`SonosController._sync_view` — clear the shared cache, then poll THROUGH
the specific speaker/coordinator the read is ABOUT — instead of clearing
once and reading an arbitrary member. `topology`'s and `stop-all`'s
per-group rows are therefore each read from THAT row's own coordinator,
at the moment they're read — not one atomic snapshot across the whole
household; two rows can reflect two different instants. `stop-all`,
`restore-state`, `group`, `mute-all`, and `save-state` also retry
transient network errors (`OSError`, `requests`' `ConnectionError`, and
`SoCoUPnPException` for the transient UPnP 701) up to 3 times with a short
backoff — the same WSL2-host flakiness class Flight 1's debrief recorded.
`restore-state`'s final match report additionally settle-polls each
speaker's row (squawk 0007): a mismatch right after the joins can be pure
view lag rather than a real restore failure, so each row is cleared and
re-read, through that speaker's own view, until it matches expected or
`SYNC_VIEW_TIMEOUT_SECONDS` elapses, before being recorded as a mismatch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import requests
from fastmcp import Client
from soco.exceptions import SoCoSlaveException, SoCoUPnPException

from mcp_sonos.controller import (
    SYNC_VIEW_POLL_INTERVAL_SECONDS,
    SYNC_VIEW_TIMEOUT_SECONDS,
    GroupingError,
    SonosController,
    _coordinator_of,
    _group_members_of,
)
from mcp_sonos.server import mcp, register_tools

DEFAULT_STREAM_URL = "http://ice1.somafm.com/groovesalad-128-mp3"

# Leg 4: bound for transient-network-error retries (save-state, mute-all,
# group, restore-state) AND for stop-all's SoCoSlaveException-or-transient
# retry on each coordinator's stop() call.
TRANSIENT_RETRIES = 3
TRANSIENT_BACKOFF_SECONDS = 0.5

controller = SonosController()
register_tools(mcp, controller)


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _speakers_by_name() -> dict[str, "SoCo"]:
    return {s.player_name: s for s in controller._speakers_fresh()}


def _is_transient_error(exc: Exception) -> bool:
    """True for the WSL2-host-flakiness error classes leg 4 targets: a raw
    socket/OS error, `requests`' own `ConnectionError`, or a UPnP 701
    ("Transition not available") — almost always residual state from a
    just-prior mutation, not a real failure."""
    if isinstance(exc, (OSError, requests.exceptions.ConnectionError)):
        return True
    if isinstance(exc, SoCoUPnPException) and str(getattr(exc, "error_code", "")) == "701":
        return True
    return False


def _retry_transient(fn, *, retries: int = TRANSIENT_RETRIES, backoff: float = TRANSIENT_BACKOFF_SECONDS):
    """Call `fn()`, retrying up to `retries` times ONLY for
    `_is_transient_error` exceptions, with a short linear backoff. A
    non-transient exception propagates immediately (no retry); the last
    transient exception propagates if every attempt is exhausted."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if not _is_transient_error(e):
                raise
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc


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
        # Leg 4: retry transient network errors on each per-speaker read.
        volume = _retry_transient(lambda s=s: s.volume)
        muted = _retry_transient(lambda s=s: s.mute)
        per_speaker[s.player_name] = {"volume": volume, "muted": muted}
    for g in groups.values():
        g["members"].sort()
    data = {"groups": sorted(groups.values(), key=lambda g: g["coordinator"]), "speakers": per_speaker}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    _emit(data)


def _read_speaker_row(s: "SoCo") -> tuple[int, bool, list[str], str]:
    """One live-read attempt of `s`'s volume/mute/group-membership row.

    Syncs `s`'s OWN view (leg 4 invariant) before reading its group, so the
    read comes from `s` itself rather than a cached view SoCo last polled
    through some other (possibly lagging) speaker. Transient network errors
    on the volume/mute reads are retried via `_retry_transient`; a
    `GroupingError` or other exception from the sync/group read propagates
    to the caller.
    """
    volume = _retry_transient(lambda: s.volume)
    muted = _retry_transient(lambda: s.mute)
    controller._sync_view(s)
    coord = _coordinator_of(s)
    actual_members = sorted(_group_members_of(coord))
    return volume, muted, actual_members, coord.player_name


def cmd_restore_state(path: str) -> None:
    """Restore groups + volume/mute from `path`; always prints a live
    re-read match report (leg 4: even a speaker unreadable after retries is
    reported, not fatal to the report as a whole). Exits non-zero only if a
    mismatch or unreadable speaker remains in that report."""
    with open(path) as f:
        data = json.load(f)

    by_name = _speakers_by_name()

    # 1. Unjoin every speaker — everyone starts standalone.
    for s in by_name.values():
        try:
            _retry_transient(lambda s=s: s.unjoin())
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
            try:
                _retry_transient(lambda m=m, coord=coord: m.join(coord))
            except Exception:
                pass  # best-effort; the live re-read below reports any mismatch
    time.sleep(0.5)

    # 3. Restore volume + mute.
    for name, state in data["speakers"].items():
        s = by_name.get(name)
        if s is None:
            continue
        try:
            _retry_transient(lambda s=s, state=state: setattr(s, "volume", state["volume"]))
            _retry_transient(lambda s=s, state=state: setattr(s, "mute", state["muted"]))
        except Exception:
            pass  # best-effort; reported per speaker in the match report below

    # 4. Live re-read match report — never an echo of the file. Always
    # produced in full: a speaker that's unreadable even after retries is
    # reported as such (not skipped, and doesn't abort the rest).
    controller._clear_socos_zgs_cache(list(by_name.values()))
    expected_group_of: dict[str, list[str]] = {}
    for g in data["groups"]:
        for name in g["members"]:
            expected_group_of[name] = sorted(g["members"])

    report = []
    any_unmatched = False
    for name, state in data["speakers"].items():
        s = by_name.get(name)
        if s is None:
            report.append({"speaker": name, "matched": False, "reason": "not found"})
            any_unmatched = True
            continue
        expected_members = expected_group_of.get(name, [name])

        # Settle-poll (squawk 0007): a mismatch right after the joins can be
        # pure view lag rather than a real restore failure — `topology` and
        # `stop-all` already read each row through a fresh, speaker-owned
        # view, but a single such read can still land before that speaker's
        # OWN view has caught up with the just-made group change. Clear the
        # cache and re-read through `s`'s own view, same as those two
        # commands, repeating until it matches expected or a short cap
        # elapses, before recording it as a mismatch. `_retry_transient`
        # (inside `_read_speaker_row`) still separately retries each
        # individual volume/mute read against transient network errors.
        last_exc: Exception | None = None
        volume = muted = coord_name = None
        actual_members: list[str] = []
        matched = False
        deadline = time.monotonic() + SYNC_VIEW_TIMEOUT_SECONDS
        while True:
            try:
                volume, muted, actual_members, coord_name = _read_speaker_row(s)
                last_exc = None
                matched = (
                    volume == state["volume"]
                    and muted == state["muted"]
                    and actual_members == expected_members
                )
            except Exception as e:
                last_exc = e
                matched = False
            if matched or time.monotonic() >= deadline:
                break
            time.sleep(SYNC_VIEW_POLL_INTERVAL_SECONDS)
        if last_exc is not None:
            report.append(
                {"speaker": name, "matched": False, "reason": f"unreadable after retries: {last_exc}"}
            )
            any_unmatched = True
            continue
        if not matched:
            any_unmatched = True
        report.append(
            {
                "speaker": name,
                "matched": matched,
                "volume": volume,
                "expected_volume": state["volume"],
                "muted": muted,
                "expected_muted": state["muted"],
                "coordinator": coord_name,
                "group_members": actual_members,
                "expected_group_members": expected_members,
            }
        )
    _emit({"restored_from": path, "report": report})
    if any_unmatched:
        sys.exit(1)


def cmd_mute_all() -> None:
    speakers = controller._speakers_fresh()
    for s in speakers:
        _retry_transient(lambda s=s: setattr(s, "mute", True))
    _emit({"muted": [s.player_name for s in speakers]})


def _coordinators_of(speakers: list) -> dict[str, "SoCo"]:
    """Dedup `speakers` down to one entry per distinct coordinator UID,
    preserving first-seen order. Shared by `topology` and `stop-all` (leg
    4) so both walk the SAME "one row per coordinator" shape."""
    coords: dict[str, "SoCo"] = {}
    for s in speakers:
        coord = _coordinator_of(s)
        coords.setdefault(coord.uid, coord)
    return coords


def cmd_topology() -> None:
    """Each group's coordinator/members/state/uri. Leg 4: each row is read
    from THAT row's own coordinator's view (`_sync_view`'d immediately
    before the row's state/uri/members are read) — not one atomic snapshot
    across the whole household. Two rows in the same output can therefore
    reflect two different instants if topology is churning."""
    speakers = controller._speakers_fresh()
    controller._clear_socos_zgs_cache(speakers)
    coords = _coordinators_of(speakers)

    groups: dict[str, dict] = {}
    for coord_uid, coord in coords.items():
        controller._sync_view(coord)
        try:
            state = coord.get_current_transport_info().get("current_transport_state")
        except Exception:
            state = None
        try:
            uri = coord.get_current_track_info().get("uri")
        except Exception:
            uri = None
        groups[coord_uid] = {
            "coordinator": coord.player_name,
            "members": sorted(_group_members_of(coord)),
            "state": state,
            "uri": uri,
        }
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
            _retry_transient(lambda n=n: resolved[n].unjoin())
        except Exception:
            pass
    time.sleep(0.3)

    coord = resolved[coordinator]
    for m in members:
        _retry_transient(lambda m=m, coord=coord: resolved[m].join(coord))
    time.sleep(0.3)

    controller._clear_socos_zgs_cache(list(resolved.values()))
    # Read the result from the coordinator's OWN view (leg 4 invariant).
    controller._sync_view(coord)
    _emit({"coordinator": coord.player_name, "group_members": sorted(_group_members_of(coord))})


def cmd_stop_all() -> None:
    """Stop every group's coordinator. Leg 4: syncs each coordinator's own
    view before stopping it, retries a `SoCoSlaveException` (with a resync)
    or a transient network error up to `TRANSIENT_RETRIES` times, and never
    silently swallows a failure — it's collected into `errors`. Afterwards,
    re-reads every coordinator's own (freshly synced) state; exits non-zero
    and lists the offenders in `still_playing` if any is still PLAYING.
    Always prints its full JSON report to stdout first, regardless of exit
    code."""
    speakers = controller._speakers_fresh()
    controller._clear_socos_zgs_cache(speakers)
    coords = _coordinators_of(speakers)

    stopped: list[str] = []
    errors: list[dict] = []
    for coord_uid, coord in coords.items():
        controller._sync_view(coord)
        last_exc: Exception | None = None
        ok = False
        for attempt in range(TRANSIENT_RETRIES):
            try:
                coord.stop()
                ok = True
                break
            except SoCoSlaveException as e:
                last_exc = e
                try:
                    controller._sync_view(coord, expect_coordinator=True)
                except GroupingError as sync_err:
                    last_exc = sync_err
                    break
            except Exception as e:
                last_exc = e
                if not _is_transient_error(e):
                    break
            if attempt < TRANSIENT_RETRIES - 1:
                time.sleep(TRANSIENT_BACKOFF_SECONDS * (attempt + 1))
        if ok:
            stopped.append(coord.player_name)
        else:
            errors.append({"coordinator": coord.player_name, "error": str(last_exc)})

    # Re-read every coordinator's own state afterward — the stop attempts'
    # own apparent success is never trusted as the final word.
    controller._clear_socos_zgs_cache(speakers)
    still_playing: list[str] = []
    for coord_uid, coord in coords.items():
        controller._sync_view(coord)
        try:
            state = coord.get_current_transport_info().get("current_transport_state")
        except Exception:
            state = None
        if state == "PLAYING":
            still_playing.append(coord.player_name)

    _emit({"stopped": stopped, "errors": errors, "still_playing": still_playing})
    if still_playing:
        sys.exit(1)


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

    sub.add_parser(
        "topology",
        help=(
            "Print each group's coordinator, members, state, and uri. Each row is "
            "read from THAT row's own coordinator's view, at the moment it's read "
            "— not one atomic snapshot of the whole household."
        ),
    )

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

    sub.add_parser(
        "stop-all",
        help=(
            "Stop every group's coordinator, syncing each one's own view first and "
            "retrying transient failures. Always prints stopped/errors/still_playing; "
            "exits non-zero if any group is still PLAYING after the re-check."
        ),
    )

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
