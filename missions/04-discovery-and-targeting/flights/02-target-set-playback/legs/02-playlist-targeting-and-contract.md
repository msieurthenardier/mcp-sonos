# Leg: playlist-targeting-and-contract

**Status**: completed
**Flight**: [Deterministic Target-Set Playback](../flight.md)

## Objective
Finish the target-set contract:
- `playlist_play` and `playlist_from_page` take `speakers` + `detach`, going
  through leg 01's plan/execute engine.
- Playlist control tools find a session from any member of the target group.
- The README agent system prompt and CLAUDE.md describe the final contract.
- Version goes to 0.5.0.
- Build the `targeting_smoke.py` behavior-test apparatus.

## Context
- Leg 01 landed (uncommitted, 152 passed). It provides:
  - `SonosController._plan_targets(names, *, detach)`
  - `_execute_plan(ctx) -> TargetGroup(coordinator, members, stopped, detached)`
  - `GroupingError`
  - the `SpeakerTargets` / `DetachFlag` annotated types in `server.py`
  - `FakeHousehold` in `tests/_fakes.py`

  Read the leg 01 flight-log entry first.
- Flight design decisions that apply:
  - **"Playlist sessions"**: sessions are keyed by `c0`'s UID, the group is
    formed once and not re-imposed, and the control-tool lookup fallback.
  - **"Plan / execute split"**: playlists call plan then execute directly,
    with no resume wrapper, deliberately.
  - **"Tool response shape"**
  - **"Behavior-test apparatus"**, including the subcommand list and the
    restore algorithm
  - **"Version"**
- `PlaylistManager.play(speaker_name, ...)` resolves by name and keys the
  worker session by that speaker's UID. Passing `c0.player_name` makes `c0`
  the "named speaker", which preserves the speaker-UID keying invariant.
- `SonosController._with_queue_resume` checks
  `self.playlists.has_active_session(c0.uid)`. Once worker sessions are keyed
  by `c0`, that check stays correct.
- **Hardware contact is limited** to one permitted read-only check:
  `targeting_smoke.py topology`, which only reads. Do **not** run any
  subcommand that mutates state (stream, say, group, stop-all, mute-all,
  restore-state); leg 03 runs those under the behavior test.

## Inputs
- The working tree after leg 01, with 152 tests passing.

## Outputs
- `mcp_sonos/controller.py`: `playlist_play`, plus `playlist_from_page`
  target support
- `mcp_sonos/playlists.py`: the control-tool session-lookup fallback
- `mcp_sonos/server.py`
- `mcp_sonos/__init__.py`
- `tests/test_version.py`
- New or updated playlist-targeting tests
- `README.md` (the full system prompt and tool list), `CLAUDE.md`
- `targeting_smoke.py` (new), and argument updates in `playlist_smoke.py`,
  `queue_smoke.py` and `reap_smoke.py`

## Acceptance Criteria

**Playlist targeting**
- [ ] `SonosController.playlist_play(speakers, name, *, shuffle=False,
  start_index=0, detach=True)`:
  1. calls `_plan_targets`, then `_execute_plan`
  2. calls `self.playlists.play(c0.player_name, name, shuffle=...,
     start_index=...)`
  3. returns the engine's dict merged with `targets`, `coordinator`,
     `group_members`, `stopped` and `detached`, keeping `engine`
  - The engine's `speaker` key equals `coordinator`, because `c0` is the
    named speaker. Keep both, and note why in the docstring.
- [ ] The `playlist_play` tool takes `speakers: SpeakerTargets` +
  `detach: DetachFlag` and delegates to `controller.playlist_play`, so no
  logic lives in `server.py`.
- [ ] `playlist_from_page` takes optional `speakers: list[str] | None` +
  `detach`.
  - When given, it plays through the same path as `playlist_play`.
  - The response gains the target keys.
  - When omitted, it only builds the playlist, as today.
- [ ] `"all"` passed to either playlist tool raises `ValueError`, with the
  same message leg 01 uses for non-`say` tools.

**Session lookup fallback (`playlists.py`)**
- [ ] `next_track`, `previous_track`, `stop` and `status` look up
  `self._sessions.get(speaker.uid)`. If that misses, they try
  `self._sessions.get(coord.uid)`, the named speaker's current coordinator.
  Only when both miss do they take today's "no worker session" path.
- [ ] Factor this into one private helper, `_session_for(speaker, coord)`,
  used by all four methods.
- [ ] Unit tests:
  - A worker session keyed by `c0`, where `playlist_stop` names a follower
    of `c0`, signals the session. It does not take the "no worker session"
    path.
  - The same applies to `status` and `next_track`.
  - A speaker in an unrelated group still gets today's no-session path.
  - `previous_track` is covered too, so every call site that uses the
    helper is tested.
  - Existing playlist tests stay green, with assertions unchanged.
- [ ] **Accepted limitation, documented in the CLAUDE.md caveats.**
  - The fallback only recovers a session when the named speaker's
    *current* coordinator is `c0`.
  - If `c0` is later made a follower of another coordinator outside this
    MCP, through the raw `group` tool or the Sonos app, control tools
    naming that new group miss the session.
  - In practice the worker's URI-mismatch takeover detection usually ends
    the session within one poll. State this as the same best-effort class
    as the existing "grouping changes" resume caveat.

**Contract docs + version**
- [ ] `mcp_sonos/__init__.py` has `__version__ = "0.5.0"`, and
  `tests/test_version.py` asserts `0.5.0`. The version appears nowhere else.
- [ ] The README "System prompt for your agent" block is rewritten for the
  target-set contract.
  - **Tools list**: `play_url(speakers[], url, title?, detach?)` and the
    other audio tools, with the new signatures.
  - **A new usage rule**: "To play on specific speakers, pass them all in
    `speakers`. By default exactly those speakers play. Anything they were
    grouped with is stopped and separated, and other groups are untouched.
    Pass `detach: false` only when you want each target's existing group to
    play too."
  - **"Play X everywhere"**: pass every speaker from `list_speakers` in
    `speakers`. Use `say(["all"])` for announcements. Stop recommending
    `partymode` followed by `play_url`.
  - **"Stop everything"** stays per coordinator.
  - The **auto-resume** text is updated. The queue resumes on the resulting
    coordinator when that coordinator was already leading its group, and
    stopped bystanders are not resumed.
  - **Error handling**: add `NoSpeakersFound`, meaning discovery failed, so
    surface its hints. Add `GroupingError`, meaning topology is in the
    message, so read it and retry or report.
  - **Tools list**: include `playlist_from_page(name, page_url, …,
    speakers?, detach?)`. It was missing from the prompt before this
    flight.
- [ ] README tool-list lines for the playlist tools are updated, and there
  are no stale `speaker`-singular signatures for audio tools anywhere in the
  README.
- [ ] CLAUDE.md:
  - Session keying, "Worker sessions are keyed by c0 …", now covers target
    sets and the control-tool coordinator fallback.
  - Caveats are updated.
  - Anything leg 01 wrote is reconciled.

**Apparatus (`targeting_smoke.py`, repo root)**
- [ ] It follows the other smoke scripts' pattern: an in-process FastMCP
  `Client` plus `register_tools`, and the controller where direct SoCo
  access is needed for save and restore.
- [ ] It has these subcommands:
  - `save-state FILE`: JSON of groups (coordinator, members) plus each
    speaker's volume and mute.
  - `restore-state FILE`:
    1. unjoin every speaker
    2. for each saved group of two or more, join each member to its
       coordinator, standalone-then-join
    3. restore volume and mute
    4. print a per-speaker match report built from a **live re-read** of
       each speaker's volume, mute and group after setting them, not an
       echo of the file
  - `mute-all`
  - `topology`: prints JSON for each group with `coordinator`, `members`,
    and the **coordinator's** `state` and `uri`. It clears SoCo's ZGS cache
    before reading.
  - `group COORD [MEMBERS...]`: unjoins each named speaker, then joins
    each member to `COORD`. It never calls the `group` tool (squawk 0006).
  - `stream --speakers A [B...] [--no-detach] [--url URL]`: calls the
    `play_stream` tool. The default URL is
    `http://ice1.somafm.com/groovesalad-128-mp3`.
  - `say --speakers A [B...] --text T`: calls the `say` tool, passing the
    `--speakers` values **through unchanged** as the list. `all` alone
    becomes `["all"]`; `all Kitchen` becomes `["all", "Kitchen"]`, and the
    tool's own validation rejects it. The script does not special-case
    `"all"`.
  - `stop-all`: stops each group's coordinator.
- [ ] Each subcommand prints its tool result or read as one JSON document
  on stdout. On a tool error it prints the error text to stderr and exits
  non-zero. It sets no environment defaults.
- [ ] The behavior-test spec `tests/behavior/target-set-playback.md` matches
  the apparatus's real subcommand names and flags. If a flag differs, update
  the spec text to match, and note it in the flight log.

**Consumers + suite**
- [ ] `playlist_smoke.py`, `queue_smoke.py` and `reap_smoke.py` call
  `playlist_play` with `speakers`. Update the arguments only; do not run
  them.
- [ ] `timeout 180 .venv/bin/python -m pytest -q` passes with more than 152
  tests, and no assertion is weakened.

## Verification Steps
- `timeout 180 .venv/bin/python -m pytest -q`
- `grep -n "speaker: SpeakerName" mcp_sonos/server.py`: control tools only
  (`now_playing`, transport, volume, `reboot`, grouping, and playlist
  `next`/`previous`/`stop`/`status`)
- `grep -n "play_url(speaker\|play_file(speaker\|play_stream(speaker\|playlist_play(speaker\|say(target" README.md`:
  empty. The Roadmap's speculative `play_radio(speaker, …)` is exempt, but
  reword it if you're in the area.
- `grep -rn "0\.4\.0" mcp_sonos tests/*.py`: empty. Historical
  behavior-test run logs under `tests/behavior/**/runs/` legitimately say
  0.4.0 and are excluded.
- `timeout 60 .venv/bin/python targeting_smoke.py topology`: exits 0 and
  prints groups with coordinator state. This is the only permitted hardware
  contact, and it is read-only.
- `timeout 60 .venv/bin/python targeting_smoke.py --help`: lists every
  subcommand.

## Implementation Guidance
1. Add the `playlists.py` `_session_for` helper and its tests first. They
   are independent of targeting.
2. Add the controller `playlist_play` and `playlist_from_page` targeting,
   update the server schema, and write the tests with `FakeHousehold`.
3. Bump the version.
4. Write the README system prompt and CLAUDE.md. Remove numbers from prose
   wherever you can, a project lesson; for example, don't restate a tool
   count.
5. Write `targeting_smoke.py` and reconcile the behavior-test spec.
6. Update the smoke-script arguments.

## Edge Cases
- **`playlist_play` on a target set whose `c0` already has a worker
  session.** `PlaylistManager.play` already stops a previous session keyed
  on the same UID. Keep that behavior.
- **Native-queue engine.** The queue is loaded on `c0`, the coordinator.
  Control-tool calls on any member reach it through the coordinator, as
  today, and the fallback is only needed for the worker engine.
- **`playlist_from_page(speakers=[])`**: treat it the same as omitted, or
  reject it with `min_length`. Pick one, document it, and test it.

## Files Affected
- `mcp_sonos/controller.py`, `mcp_sonos/playlists.py`,
  `mcp_sonos/server.py`, `mcp_sonos/__init__.py`
- `tests/test_version.py`, plus new playlist-targeting and
  session-fallback tests
- `README.md`, `CLAUDE.md`
- `targeting_smoke.py` (new), `playlist_smoke.py`, `queue_smoke.py`,
  `reap_smoke.py`
- `tests/behavior/target-set-playback.md`, only if the apparatus flags
  differ

## Citation Audit (2026-09-29)
Each citation was checked against the working tree after leg 01:
- `playlists.py:PlaylistManager`
  - `play(speaker_name, playlist_name, shuffle, start_index)`
  - `_play_via_worker`: sessions keyed by `speaker.uid`
  - `next_track`, `previous_track`, `stop`, `status`: each does
    `sess = self._sessions.get(speaker.uid)`
  - `has_active_session(speaker_uid)`
  - `_worker`: re-resolves `session.speaker_name` each track
- `controller.py:playlist_from_page(..., speaker: str | None = None)`:
  `self.playlists.play(speaker, playlist)`
- `server.py`: `playlist_play(speaker: SpeakerName, ...)` returns
  `controller.playlists.play(...)`

All were found.

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
