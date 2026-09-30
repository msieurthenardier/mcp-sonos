# Leg: target-group-engine

**Status**: completed
**Flight**: [Deterministic Target-Set Playback](../flight.md)

## Objective
Build the target-set grouping engine:
- the pure planner in `mcp_sonos/targeting.py`
- the controller's `_plan_targets` / `_execute_plan`, with poll-confirmation
  and `GroupingError`

Then move `play_url`, `play_file`, `play_stream` and `say` to
`speakers: list[str]` + `detach: bool = True`, keeping the `say(["all"])`
sentinel. Carry the queue-resume on `c0` and the new response shape. Include
their tests and their tool descriptions.

## Context
- **The flight's Design Decisions are the authoritative spec.** Read them in
  full first. In particular:
  - "Firmware grouping semantics": hardware-verified, with the executor
    invariant **never `join()` a speaker that coordinates others**
  - "Detach algorithm", "Coordinator choice", "Opt-out semantics"
  - "Plan / execute split around queue resume"
  - "Topology confirmation", "Partial failure", "Tool response shape"
  - "`say(["all"])` sentinel", "Tool contract"
- Flight 1 learnings that apply:
  - SoCo's 5 s `ZoneGroupState` cache must be cleared before every topology
    read and poll.
  - Use `_resolve`, which has the name-miss retry, and let `NoSpeakersFound`
    propagate unwrapped.
  - Use the controller's injectable `self._sleep` for waits, so tests stay
    fast.
- CLAUDE.md invariants: every `.group.coordinator` / `.group.members` read
  goes through `_coordinator_of` / `_group_members_of`. No business logic in
  `server.py`. Keep speaker-UID session keying.
- **Do not contact the Sonos speakers.** Leg 03 is hardware verification.
  All tests must be hardware-free.
- Playlists (`playlist_play`, `playlist_from_page`) are **leg 02**. Leave
  their signatures unchanged here. The version bump, README system-prompt
  rewrite and `targeting_smoke.py` are also leg 02.

## Inputs
- Branch `flight/02-target-set-playback` at `a15392f`, with 118 tests
  passing.

## Outputs
- `mcp_sonos/targeting.py` (new)
- `mcp_sonos/controller.py`
- `mcp_sonos/server.py`
- `tests/_fakes.py`
- `tests/test_targeting.py` (new)
- `tests/test_target_group_controller.py` (new, or fold into
  `test_targeting.py`)
- Updated consumers: `tests/test_queue_resume.py`,
  `tests/test_say_coordinator.py`, `tests/test_discovery.py`, and the four
  hardware smoke scripts, wherever they call the changed methods

## Acceptance Criteria

**Planner (`mcp_sonos/targeting.py`)**, a pure, I/O-free, cycle-free leaf
module:
- [ ] `plan_target_group(topology, targets, *, detach) -> TargetPlan`.
  - `topology` is a list of groups, each with `coordinator_uid`,
    `member_uids` and the coordinator's `state`.
  - `targets` is the resolved target UIDs, in order.
  - The plan carries:
    - `coordinator_uid`
    - `stop`: the coordinators to stop
    - an ordered `unjoin` list
    - an ordered `join` list
    - `bystanders`
    - `untouched_groups`
    - `fast_path`: bool
    - **`final_members`**, the expected final membership of `c0`'s group.
      This field is required, not an acceptable variation.
      - For `detach=True` it equals the targets.
      - For `detach=False` it is the union of every affected group's
        pre-plan membership, including pulled-in non-targets.
- [ ] Coordinator choice follows the flight's four-rule precedence exactly.
- [ ] `detach=True` follows the "Detach algorithm", including the explicit
  order of the "Separate" steps. Groups with no target appear in no list.
- [ ] `detach=False` follows "Opt-out semantics":
  - one group, or a single target, produces no changes
  - multiple groups merge, joining followers before their old coordinator
  - nothing is stopped
- [ ] **Invariant enforced in the planner.** No UID in `join` coordinates
  other members at the point its join executes. Given the plan's own
  earlier unjoins, every joiner is standalone.

**Controller**
- [ ] `_plan_targets(names, *, detach)` is read-only. It:
  1. resolves each name via `_resolve` (an unknown name raises
     `SpeakerNotFound` before any mutation, and `NoSpeakersFound`
     propagates)
  2. de-duplicates by UID, keeping the first occurrence
  3. calls `zone_group_state.clear_cache()` once per household
  4. snapshots the topology via `_coordinator_of` / `_group_members_of`,
     plus each affected coordinator's transport state
  5. calls the planner
- [ ] `_execute_plan(plan)` issues the stops, then the unjoins, then the
  joins, then confirms.
  - Confirmation polls every 0.1 s with `self._sleep`, clearing the cache
    before each read, with a 5 s cap, until `c0`'s group equals
    **`plan.final_members`**. That is the flight's "planned membership", not
    the target set; for `detach=False` merges the final group is larger than
    the targets.
  - It then reads each bystander's current coordinator state once,
    cache-cleared, and raises `GroupingError` if any is `PLAYING`.
  - It returns `TargetGroup(coordinator, members, stopped, detached)`.
- [ ] `GroupingError(RuntimeError)`, raised on a mid-execution exception or
  a confirmation timeout. It names the failing step, the targets, and the
  observed topology of the involved speakers from a cache-cleared read. No
  rollback.
- [ ] `play_url(names, url, title=None, *, detach=True)` and `say(names,
  text, *, volume=None, lang="en", detach=True)` call `_plan_targets` and
  then `_with_queue_resume(c0, c0.uid, run_clip)`, where `run_clip` runs
  `_execute_plan`, then plays.
  - The snapshot therefore sees `c0`'s pre-stop `PLAYING` state.
  - A snapshot happens only if `c0` was a coordinator before the call.
- [ ] `say`'s stale-coordinator retry `resolve` re-resolves `c0` by its
  player name.
- [ ] `say`'s `volume` applies to exactly `final_members`. With
  `detach=False`, that includes pulled-in non-target members, because they
  are playing. It never includes stopped bystanders.
- [ ] `say(["all"])` (case-insensitive) takes the unchanged `_say_all` path.
  - `"all"` mixed with names raises `ValueError`.
  - `"all"` passed to any tool other than `say` raises `ValueError`, with a
    message pointing to `say` or `list_speakers`.
- [ ] `play_stream(names, url, title=None, *, detach=True)` calls
  `_plan_targets`, then `_execute_plan`, then the existing plain→radio
  scheme logic on `c0`.
- [ ] `play_file` delegates to `play_url` with `speakers` and `detach`.
- [ ] Response shape, for all four tools:
  - `targets`, `coordinator`, `group_members`, `stopped` and `detached`
  - existing tool-specific keys such as `url`, `scheme`, `text` and track
    state are kept
  - `requested`, `played_on_coordinator` and `spoken_on` are replaced
  - `say(["all"])` keeps its existing return shape

**Server**
- [ ] `play_url`, `play_file`, `play_stream` and `say` take `speakers:
  Annotated[list[str], Field(min_length=1, description=...)]` and
  `detach: Annotated[bool, Field(description=...)] = True`.
  - The descriptions state the detach-default semantics, that stop-first
    silences bystanders, and that `detach=false` merges groups and pulls in
    their non-target members.
  - `say`'s description documents `["all"]`.
  - Each tool body is still a single delegation.
- [ ] Control tools stay single-speaker and unchanged.

**Tests**
- [ ] `tests/_fakes.py` models the hardware-verified semantics **without
  changing any existing test's behavior**. The recommended shape is an
  opt-in `FakeHousehold` that owns group membership. `SoCoFake.join` /
  `unjoin` delegate to it when attached, and keep today's behavior when
  unattached. The household model:
  - `join` moves only `self`
  - a coordinator's `unjoin()` delegates its remaining members to the first
    remaining member
  - `join()` on a speaker that coordinates others **raises** `AssertionError`
  - `stop()` on a coordinator marks its group stopped
  - a follower's `join()` or `unjoin()` also removes it from its previous
    group's member list, which is never left stale
- [ ] `tests/test_targeting.py` exhaustively covers the planner:
  - the exact-match fast path, including idempotence
  - all four coordinator rules
  - rule 2 when `c0`'s own group has bystanders
  - a target that is a follower of a bystander coordinator
  - a non-`c0` target that coordinates two or more bystanders (delegated,
    stays grouped)
  - untouched groups
  - duplicates
  - opt-out: single, same-group, and a multi-group merge that joins
    followers before the old coordinator
  - the invariant that no join targets a speaker coordinating others
- [ ] Controller tests use `FakeHousehold`:
  - stop happens before any unjoin
  - untouched groups receive **zero** calls
  - an unknown name raises `SpeakerNotFound` with **zero** mutation calls
  - a mid-step exception raises `GroupingError`, and its message contains
    the topology
  - a confirmation timeout raises `GroupingError`, using `self._sleep`
    patched to a no-op
  - a bystander still `PLAYING` raises `GroupingError`
  - the queue snapshot is taken before stop when rule 2 picks a `c0` with
    bystanders, and the resume lands on `c0`
  - `say(["all"])` still dissolves and returns the old shape
  - `"all"` mixed with names raises
  - `say` volume applies only to target-group members
- [ ] Existing tests are updated for the new signatures, renamed rather than
  weakened, and no assertion is loosened.
  - **One known value change.**
    `tests/test_discovery.py::test_say_inline_retry_clears_socos_cache`
    asserts `clear_cache_count == 1`. `_plan_targets` now also clears the
    cache before its snapshot, so the stale-coordinator path legitimately
    clears it at least twice.
    - Update the assertion to the new exact count.
    - Keep the test's intent, "the retry clears SoCo's cache", for example
      by also asserting that a clear happened *after* the
      `SoCoSlaveException`.
    - Note the change in the flight log. This is a behavior increase, not a
      loosening.
- [ ] `timeout 180 .venv/bin/python -m pytest -q` passes, with more than 118
  tests.

**Docs, for these four tools only**
- [ ] The README tool list entries for `play_url`, `play_file`,
  `play_stream` and `say` show the new signatures. The full system-prompt
  rewrite is leg 02.
- [ ] CLAUDE.md gains:
  - an architecture note on `targeting.py` as a planner/executor split
  - the invariant "grouping: never `join()` a speaker that coordinates
    others; clear SoCo ZGS cache before topology reads"
  - a caveats note on `detach` semantics

## Verification Steps
- `timeout 180 .venv/bin/python -m pytest -q`
- `grep -n "speakers:" mcp_sonos/server.py`: expect exactly the four tools
  (playlists are leg 02)
- `grep -n "def plan_target_group" mcp_sonos/targeting.py`. Then check the
  module is pure: `grep -n "import soco\|from soco" mcp_sonos/targeting.py`
  should return nothing.
- `.venv/bin/python -c "import mcp_sonos.server"` imports cleanly.

## Implementation Guidance
1. **Write `targeting.py` and `test_targeting.py` first.** The planner is
   pure. Get every topology case green before touching the controller.
2. **Add `FakeHousehold` to `tests/_fakes.py`**, then run the existing suite
   to confirm nothing changed.
3. **Controller**:
   - `_plan_targets` and `_execute_plan`, then `GroupingError`.
   - Rewire `play_url`, `play_stream`, `play_file` and `say`.
   - Keep `_with_queue_resume`'s signature. The grouping happens inside the
     `run_clip` callable that is passed to it.
4. **Server** schema changes.
5. **Update test consumers and smoke scripts** for the new signatures.
   `smoke_test.py`, `queue_smoke.py`, `playlist_smoke.py` and `reap_smoke.py`
   call `say`, `play_url` and friends via the MCP client. Update their
   arguments; do not run them.
6. **Docs.**

## Edge Cases
- **Opt-out merge mechanism (hardware-verified 2026-09-29, 3 of 3
  trials).** Peel each follower of a merged group off with `join(c0)`. Its
  old coordinator is then standalone, and its `join(c0)` settles in about
  0.15 s. This is exactly the planned "followers first, old coordinator
  last" sequence.
- **Duplicate names**, including different case: dedupe by UID and keep the
  first.
- **`speakers=[]`**: rejected at the tool boundary (`min_length=1`), and
  with `ValueError` in the controller.
- **Target set equals an existing group with a different coordinator
  order**: take the fast path, keep the existing coordinator, and report it
  in `coordinator`.
- **All targets are standalone and idle**: no stops. Joins to `c0`, the
  first listed target, following the rules.
- **`c0` is the coordinator of an exact-match group that is `PLAYING`**:
  the fast path means no stop. The snapshot and resume work as today.
- **A bystander group's delegate coordinator**, after a target
  coordinator's `unjoin`, is firmware-chosen. The confirmation re-reads it
  and never assumes it.

## Files Affected
- `mcp_sonos/targeting.py` (new)
- `mcp_sonos/controller.py`
- `mcp_sonos/server.py`
- `tests/_fakes.py`
- `tests/test_targeting.py` (new), plus controller-level tests
- `tests/test_queue_resume.py`, `tests/test_say_coordinator.py`, and any
  other consumer found by grep
- `smoke_test.py`, `queue_smoke.py`, `playlist_smoke.py`, `reap_smoke.py`
  (argument updates only)
- `README.md` (the tool-list lines for four tools), `CLAUDE.md`

## Citation Audit (2026-09-29)
Each citation was checked against `a15392f`, and all were found:
- `controller.py:SonosController`: `play_url`, `play_stream`, `play_file`,
  `say` (with `_play_clip` / `with_stale_coord_retry`, `resolve=lambda:
  self._resolve_coordinator(target)[1]`), `_with_queue_resume(coord,
  speaker_uid, run_clip, *, timeout)`, `_say_all`, and `group` (member loop
  `m.join(coord)`)
- `controller.py`: `_coordinator_of`, `_group_members_of`
- `server.py`: `SpeakerName`, and the `play_url`, `play_stream`,
  `play_file` and `say(target: …)` tool signatures
- `tests/_fakes.py:SoCoFake`: `join` ("Simplistic: this becomes a member of
  other's group") and `unjoin` ("Fake doesn't model multi-group state")

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
