# Flight: Deterministic Target-Set Playback

**Status**: in-flight
**Mission**: [Zero-Config Discovery & Deterministic Speaker Targeting](../../mission.md)

## Contributing to Criteria
- [ ] Every audio-sending tool (clip/file playback, stream playback, playlist playback, announcements) accepts a set of one or more target speakers
- [ ] By default, audio plays on exactly the requested target set: targets are detached from any existing groups and grouped only with each other *(behavior test `target-set-playback`)*
- [ ] By default, speakers that were grouped with a target but aren't targets end up stopped and separated from the targets, so only the targets make sound *(behavior test `target-set-playback`)*
- [ ] Speakers in groups that contained no target are untouched *(behavior test `target-set-playback`)*
- [ ] A caller can opt out of detaching and get today's behavior: each target's existing group plays as-is *(behavior test `target-set-playback`)*
- [ ] The all-speakers announcement keeps its existing broadcast behavior *(behavior test `target-set-playback`)*
- [ ] Tool schemas, README (agent system prompt), and CLAUDE.md describe the targeting behavior accurately *(targeting half of the docs criterion)*
- [ ] The unit suite covers target-set grouping without hardware, and passes *(targeting half)*

---

## Pre-Flight

### Objective
Every tool that sends audio takes a list of target speakers, and by default
plays on *exactly* that set, deterministically, in one call. The tools are
`play_url`, `play_file`, `play_stream`, `say`, `playlist_play`, and
`playlist_from_page` when it is given speakers.

The server works out the plan from the live topology:
- Stop any group that contains a non-target, so bystanders fall silent.
- Separate the targets from those groups.
- Group the targets under one coordinator.
- Play.

Groups that contain no target are never touched. `detach=false` opts out
and plays on each target's existing group, merged together. `say(["all"])`
keeps its broadcast path. The grouping logic is a pure, exhaustively
unit-tested planner, plus a thin executor that confirms the resulting
topology instead of sleeping blindly. The version goes to 0.5.0, and the
README agent system prompt is rewritten for the new contract.

### Planning Mode
The operator authorized running the whole mission autonomously
(2026-09-28). The flight skill's user-input and crew-interview phases were
therefore resolved by the Flight Director. Each choice below takes the
recommended option, with its rationale recorded, and is open to operator
override at PR review. Mission-level decisions already made by the operator
are preserved: breaking schema, detach by default, stop bystanders, controls
stay single-speaker, and keep the `"all"` sentinel.

### Open Questions
All of the mission's Flight-2 open questions are resolved in the design
decisions below.
- [x] Detach mechanics & timing → "Planner / executor split" and "Topology confirmation"
- [x] Coordinator choice → "Coordinator choice"
- [x] Opt-out with multiple targets → "Opt-out semantics"
- [x] Parameter naming → "Tool contract"
- [x] Partial failure → "Partial failure"
- [x] Resume snapshot timing → "Queue resume under detach"
- [x] Playlist sessions after group formation → "Playlist sessions"
- [x] Say-all under a list signature → decided by the operator at mission planning: kept as the `["all"]` sentinel

### Design Decisions

**Tool contract: `speakers: list[str]` (min 1) + `detach: bool = True`**
- Five tools take `speakers` in place of `speaker`: `play_url`,
  `play_file`, `play_stream`, `playlist_play`, and `playlist_from_page`
  (whose parameter is optional). `say` takes `speakers` in place of
  `target`.
- Each is a JSON list of display names, case-insensitive and in order.
  Duplicates are removed after name resolution, by UID.
- `detach: bool = True` on all of them.
- Rationale:
  - A boolean matches the operator's own framing ("optionally disconnect
    groups via a parameter … detach groups should be the default").
  - There is exactly one alternative behavior, so an enum adds nothing.
  - The name `speakers` reads naturally for one or many.
- Trade-off: breaking for existing callers, which the mission accepted.
  Controls stay single-speaker (mission constraint).
- Validation happens at the tool boundary with Pydantic `min_length=1`. The
  controller is defensive too, following the project's defense-in-depth
  pattern.

**`say(["all"])` sentinel**
- `speakers == ["all"]` (case-insensitive) takes today's `_say_all` path
  unchanged: dissolve → party → play → dissolve.
- Mixing `"all"` with names raises `ValueError` at both the tool boundary
  and the controller.
- `detach` is ignored for `["all"]` and documented as such. The broadcast is
  already whole-house.
- Only `say` accepts `"all"`. Other tools reject it, with a message pointing
  to `say` or to listing the speakers.

**Planner / executor split (new module `mcp_sonos/targeting.py`)**
- `plan_target_group(topology, target_uids, *, detach) -> TargetPlan` is a
  **pure function** over a topology snapshot.
  - The snapshot lists, per group, its coordinator UID and member UIDs.
  - The plan returns:
    - `coordinator_uid`
    - `stop`: the coordinator UIDs of groups to stop
    - `unjoin`: the UIDs to unjoin, in order
    - `join`: the UIDs to join to the coordinator
    - `bystanders`: the UIDs stopped and separated
    - `untouched_groups`
  - It performs no I/O.
- `SonosController._form_target_group(names, *, detach) -> TargetGroup`
  resolves the names via `_resolve`, which keeps the name-miss retry.
  - **Before snapshotting**, it calls `zone_group_state.clear_cache()` on one
    cached speaker per household, unconditionally on every call. That is
    the same ZGS clearing `_invalidate_speakers()` does, without zeroing the
    discovery TTL.
  - It then snapshots the topology via `_coordinator_of` /
    `_group_members_of`, following the CLAUDE.md invariant, together with
    each affected coordinator's transport state.
  - Then it plans, executes and confirms.
  - *Architect review, cycle 1, high.* Without clearing the cache first, a
    regroup made in the Sonos app or by an earlier call within 5 s would
    feed the planner stale topology. It could miss a bystander and leave it
    playing. The cost is one zone-group-state fetch per call, which is
    negligible.
- Rationale:
  - The planner's many topology cases can be tested exhaustively without
    fakes of SoCo behavior.
  - The executor stays small.
  - This mirrors Flight 1's stage-seam pattern, which the debrief marked
    worth standardizing.
- Placement: grouping logic stays in the controller layer. `targeting.py` is
  a cycle-free leaf, like `_retry.py` and `_urls.py`.

**Firmware grouping semantics (hardware-verified 2026-09-29, muted, state restored)**
- **A coordinator with followers that calls `unjoin()`**: its followers
  **stay grouped**, and the firmware elects a new coordinator. Observed:
  Fireplace Room left {Fireplace, Dining, Lounge, Patio}, and Lounge became
  coordinator of {Dining, Lounge, Patio}. They do *not* each become
  standalone.
- **A coordinator with followers that calls `join(other)`**: this is
  **unreliable**. Observed: Fireplace Room coordinating 4 called
  `join(Kitchen)`. It did not join Kitchen. Instead, coordination moved to
  Dining Room and Fireplace stayed in its old group.
- **A follower's `unjoin()`** leaves that one speaker standalone. **A
  standalone speaker's `join(c0)`** is reliable. Both were confirmed in the
  2026-09-28 regroup probe.
- **Executor invariant that follows:** **never call `join()` on a speaker
  that currently coordinates other members.** Either peel its followers off
  first, or `unjoin()` it first, which leaves its followers grouped under a
  delegate. Every `join` in a plan is issued only on a speaker the plan has
  already made standalone.
- The identity of a delegated coordinator is firmware-chosen, so plans never
  assume who coordinates a leftover bystander group.

**Detach algorithm (`detach=True`)**
Let T be the resolved target set. The affected groups are those containing
at least one target.
1. **Exact-match fast path.** If some existing group's member set equals T,
   use it unchanged. Its current coordinator stays coordinator. There are no
   topology changes, which makes the call idempotent: calling twice doesn't
   churn.
2. Otherwise the coordinator is chosen by the rule under "Coordinator
   choice" below.
3. **Stop first.** For every affected group that contains a bystander
   (a non-target), stop that group's coordinator. This happens *before* any
   unjoin, so a bystander can never be left playing the target audio, or
   the old audio.
4. **Separate**, in this order:
   1. If `c0` is a follower, `c0.unjoin()`.
   2. If `c0` coordinates bystanders, `unjoin()` each of those bystanders
      individually. They are followers, so each becomes standalone and
      stopped.
   3. For every other target that is not already a follower of `c0`,
      `unjoin()` it.
      - If it was a follower, it becomes standalone.
      - If it was a coordinator of others, its remaining members stay
        grouped under a firmware-chosen delegate, and stay stopped because
        step 3 stopped them.
   - Bystanders that are not in `c0`'s group are never unjoined. They remain
     grouped with each other, stopped. That is the minimum churn.
5. **Join.** Each target that is not yet in `c0`'s group runs `join(c0)`.
   By now every such target is standalone, per the executor invariant.
6. Groups with no target: no calls at all.

**Coordinator choice**, in precedence order:
1. In the exact-match fast path, keep the existing coordinator.
2. Otherwise, use the first-listed target that is currently a group
   coordinator **whose transport is `PLAYING`**. Its queue is live state
   worth keeping: the resume snapshot is taken on it, and it resumes on the
   new target group.
3. Otherwise, use the first-listed target that is currently the coordinator
   of an affected group containing no bystanders. It keeps its own group,
   which minimizes churn.
4. Otherwise, use the **first listed target**.
- Rationale: deterministic, documented, churn-minimizing, and it never
  discards a *target's* playing queue in favor of an idle target.
  - *Architect review, cycle 1, medium.* Without rule 2, T = [idle Kitchen,
    Patio playing a queue with Fireplace] would pick Kitchen and silently
    drop Patio's queue.
- A non-chosen target's queue, when two targets were both playing
  separately, is not resumed. That is an accepted, documented best-effort
  limit.
- The returned `coordinator` field tells the agent which speaker leads.

**Opt-out semantics (`detach=False`)**
- One target: exactly today's behavior. Play on its current group via its
  coordinator.
- Several targets already in one group: play on that group.
- Several targets in different groups: **merge**. Every target's group
  joins, whole, into the group of the first-listed target's coordinator, so
  "each target's existing group plays", together and synchronized.
  - **Mechanism** (*Architect review, cycle 1, high*): SoCo's `join()`
    moves only the speaker it is called on.
    - Calling `target.join(c0)` on a follower would strand the rest of its
      group.
    - Calling it on a coordinator does not bring its followers along.
    - So the merge calls `join(c0)` on **every member** of each non-`c0`
      affected group, individually, the same way SoCo's own `partymode()`
      does.
    - **Order: followers first, that group's old coordinator last.** Once
      its followers have left, the old coordinator is standalone, and
      joining it is reliable, per the executor invariant. The hardware
      showed that joining a coordinator that still has followers fails.
  - Non-target members of merged groups **are pulled in** and play. That is
    the literal meaning of "each target's existing group plays as-is", and
    it is the deliberate contrast with `detach=True`. The tool description
    must say so.
- Untouched groups remain untouched, and nothing is stopped.
- Rationale:
  - This reads the mission's criterion literally.
  - It is the only multi-group interpretation that doesn't play
    unsynchronized copies.
  - It needs no per-group resume bookkeeping.
- Trade-off: `detach=False` with several targets can pull whole groups
  together. The tool description says so.

**Plan / execute split around queue resume** (*Architect review, cycle 2, high*)
- `_form_target_group` is two named halves:
  - **`_plan_targets(names, detach) -> (TargetPlan, context)`** is
    read-only. It resolves the names, clears the cache, snapshots the
    topology and transport state, runs `plan_target_group`, and chooses
    `c0`. It changes nothing.
  - **`_execute_plan(plan) -> TargetGroup`** performs every mutation (stop,
    unjoin, join), then confirms.
- In `play_url`, `play_file` and `say`, the call order is:
  1. `_plan_targets`
  2. `_with_queue_resume(c0, c0.uid, run_clip=lambda: (_execute_plan(plan), play))`
- The queue snapshot therefore reads `c0`'s `PLAYING` state **before**
  stop-first runs.
- Without the split, stop-first would fail the snapshot's `PLAYING` gate
  and silently drop the queue that coordinator rule 2 exists to keep.
- `play_stream` has no resume, and `playlist_play` starts a new playlist
  rather than resuming one. Both call plan and then execute directly. This
  asymmetry is intentional.
- For `say`'s stale-coordinator retry, `resolve` re-resolves `c0` by its
  player name, the planned coordinator, rather than by the caller's list.

**Topology confirmation: poll, don't sleep (from the Flight 1 debrief)**
- After executing, the executor confirms the coordinator's group equals the
  planned membership.
  - It polls every 0.1 s, calling `zone_group_state.clear_cache()` on a
    member before each read, because of SoCo's 5 s cache.
  - The cap is 5 s, using the controller's injectable `self._sleep`.
- Measured on 2026-09-28 on the operator's hardware, over 4 × 2 regroup
  bursts:

  | Measure | Result |
  |---|---|
  | Commands | 0.75–1.10 s |
  | Settle | 0.16–0.32 s |
  | TCP anomalies | zero, under a concurrent 20 Hz probe of every speaker |

- The confirmation also reads, once and cache-cleared, each bystander's
  current coordinator transport state. If any is `PLAYING`, it raises
  `GroupingError`. The `stopped` field is computed from that verified read.
  This is cheap insurance against a delegate handoff resuming playback
  (*Architect review, cycle 2, medium*).
- No fixed sleeps are added. The existing grouping tools' sleeps are out of
  scope and stay as they are.

**Partial failure**
- Name resolution happens **before** any mutation. An unknown name raises
  `SpeakerNotFound` (a `ValueError`) with no side effects, and
  `NoSpeakersFound` propagates unwrapped, following the Flight 1 taxonomy.
- A failure mid-execution, or a confirmation timeout, raises
  `GroupingError(RuntimeError)`. The error names:
  - the step that failed
  - the target set
  - the observed topology of the involved speakers at failure time
- There is no rollback. Because stop runs first, a mid-sequence failure
  leaves at most silence and partial grouping, never unintended audio on a
  bystander. The agent can read the topology from the error and retry.
- Stale-coordinator retry: the play action, not the grouping, stays wrapped
  in `with_stale_coord_retry` for `say`, as today. Its `resolve` callback
  re-resolves the planned coordinator.

**Queue resume under detach**
- The snapshot runs on `c0` **before** any grouping change, and only if
  `c0` is at that moment the coordinator of its own group. A coordinator is
  the only speaker that owns a queue.
- The resume runs on `c0` afterwards, and `c0` is still coordinator of the
  target group. Resuming therefore restores the queue on the target set,
  not on the bystanders.
- Bystanders are never resumed; they end stopped, per the mission.
- Implementation: `_with_queue_resume` gains the grouping step inside its
  clip phase. The snapshot is taken first, then the clip phase runs "form
  group + play".
  - The `speaker_uid` passed through for the worker-session check is `c0`'s
    UID.
  - The existing four snapshot conditions are unchanged.
- When `c0` was a follower before the call, there is no snapshot and no
  resume. Its queue belonged to a bystander coordinator, now stopped.

**Playlist sessions**
- `playlist_play` forms the target group, then starts the engine on `c0`.
- Worker sessions are keyed by `c0`'s UID, preserving the speaker-UID keying
  invariant, with `c0` as the "named speaker".
- The worker keeps re-resolving `c0`'s coordinator on each track. The group
  forms once, at start, and is **not** re-imposed mid-playlist. If someone
  regroups by hand, the playlist follows `c0`, as today.
- **Control-tool lookup fallback.** `playlist_next`, `previous`, `stop` and
  `status` currently look up the session by the named speaker's UID. With a
  target set, the agent may name any member.
  - The lookup gains a fallback: when there is no session for the named
    speaker, use the session keyed by that speaker's current coordinator
    UID.
  - Without it, `playlist_stop("Patio")` on a Kitchen-keyed session would
    stop the coordinator directly, and the worker would misread that as a
    natural track end.

**Tool response shape**
- Every audio tool returns:
  - `targets`: resolved names, in order
  - `coordinator`
  - `group_members`
  - `stopped`: bystander names, possibly empty
  - `detached`: bool
- Existing tool-specific keys are kept, for example `url`, `scheme`,
  `engine` and track state.
- `requested` and `played_on_coordinator` are replaced by `targets` and
  `coordinator`, as part of the accepted breaking change.

**New shared state: none.** Following the debrief's recommendation 1, the
planner is pure and the executor reads live topology every call. There is
no cache of groups or of "previous topology".

**Behavior-test apparatus: `targeting_smoke.py` + muted speakers**
- *Act*: a root-level script driving an in-process FastMCP `Client`, with
  these subcommands:
  - `save-state FILE` / `restore-state FILE`: groups, volume and mute per
    speaker
  - `mute-all`
  - `group COORD [MEMBERS...]`. It does **not** call the existing `group`
    tool, which can `join()` a member that coordinates others; that is the
    unreliable case, and squawk 0006 tracks it. Instead it `unjoin()`s every
    named speaker, so each is standalone and their other followers are
    delegated, then `join(COORD)`s each member. All joins are therefore on
    standalone speakers.
  - `topology`
  - `stream --speakers A B [--no-detach]`
  - `say --speakers A B | all`
  - `clip --speakers A`
  - `stop-all`
- *Observe*: `topology` prints JSON with each group's coordinator, members,
  **coordinator** transport state and current URI.
  - Transport state is read through the coordinator, via the existing
    `list_groups` / `now_playing` read paths. Probing on 2026-09-28 showed
    follower-level transport state is unreliable: followers reported
    `PLAYING` while their coordinator reported `STOPPED`.
- *Restore algorithm* (*Architect review, cycle 1, medium*):
  `restore-state` first unjoins every speaker, so it starts with all
  speakers standalone. Then, for each saved group of two or more members, it
  applies the same standalone-then-join mechanism as the
  `group` subcommand. Saved single-speaker groups stay standalone. Finally it
  sets each speaker's volume and mute from the file, and reports matches
  and mismatches.
- *Audibility*: every speaker is muted for the whole test and restored
  afterwards. Transport state is the observable, so nothing plays audibly in
  the household.
  - Premise verified 2026-09-28: a muted Kitchen played a SomaFM stream
    (`http://ice1.somafm.com/groovesalad-128-mp3`, radio scheme, `PLAYING`
    in 6.3 s), and the prior state was restored.
- Rationale: stays in the shell frame, needs no restart of the operator's
  live MCP server, and has read paths that are already verified.

**Version: 0.4.0 → 0.5.0** (breaking tool schema). The README system prompt
is updated in the same flight (mission constraint).

### Prerequisites
- [x] Flight 1 landed. This branch is stacked on
  `flight/01-zero-config-discovery` (PR #11, not yet merged).
- [x] Suite green: 118 passed.
- [x] Hardware reachable. Five speakers, and the topology can be observed
  and restored.
- [x] Regroup burst is safe on this host, with no LAN disruption (see the
  probe above).
- [x] Muted stream playback works, and state can be observed through the
  coordinator.
- [x] Piper TTS voice cached from earlier `say` use. `say` is exercised muted.
- [x] No new network services or ports.

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [x] Prerequisites verified
- [x] Validation approach defined (unit suite + behavior test `target-set-playback`)
- [x] Legs defined

---

## In-Flight

### Technical Approach
1. **`mcp_sonos/targeting.py`**: the pure planner (`TargetPlan`,
   `plan_target_group`, exact-match fast path, coordinator choice, detach
   and opt-out plans).
2. **`controller.py`**:
   - `_form_target_group` and `GroupingError`
   - `play_url`, `play_file`, `play_stream` and `say` take `speakers` +
     `detach`
   - `_with_queue_resume` wraps "form group + play" after the snapshot
   - response-shape changes
3. **`server.py`**: the schema changes, with list validation and
   `"all"`-sentinel validation.
4. **Playlists**:
   - `playlist_play` and `playlist_from_page` route through a controller
     method that forms the group, then calls `PlaylistManager.play(c0)`.
   - Control-tool session-lookup fallback to the coordinator's session.
5. **Docs**:
   - The README agent system prompt is rewritten around target sets and
     `detach`, including "play everywhere" and "stop everything".
   - README tool list.
   - CLAUDE.md: the architecture note on `targeting.py`, the invariant
     "grouping read-after-write must clear the SoCo cache", and the targeting
     caveats.
   - Version 0.5.0.
6. **Tests**:
   - First, extend `tests/_fakes.py::SoCoFake.join` / `unjoin` to model the
     **hardware-verified** semantics:
     - `join` moves only `self`.
     - A coordinator's `unjoin()` leaves its remaining members grouped under
       a delegate, the first remaining member.
     - A coordinator-with-followers `join()` should raise in the fake, so
       the tests enforce the executor invariant. Without this, the
     merge and detach tests would pass against a fake that can't show the
     stranded-follower hazard. Existing assertions are unchanged.
   - `tests/test_targeting.py`: the planner, exhaustive.
   - Controller tests with `SoCoFake` groups:
     - execution order, with stop before unjoin
     - no `join` is ever issued on a speaker that coordinates others
     - a non-`c0` target coordinating two or more bystanders: they stay
       grouped under a delegate, stopped
     - `c0` chosen by rule 2 while its own group has bystanders: the
       snapshot is taken before stop, and the resume runs on `c0`
     - untouched groups get no calls
     - partial failure
     - resume on `c0`
     - the `"all"` path unchanged
   - Existing tests updated for the new signatures by renaming, not by
     weakening assertions.
7. **`targeting_smoke.py`** apparatus, then run behavior test
   `target-set-playback`.

### Checkpoints
- [ ] Planner + executor + clip/stream/say tools landed; unit suite green
- [ ] Playlists + response shape + docs + version 0.5.0 landed
- [ ] Behavior test `target-set-playback` passes on hardware, muted

### Adaptation Criteria

**Divert if**:
- Hardware shows a topology SoCo can't produce with `unjoin`/`join`, for
  example a bonded or stereo pair, which the household doesn't have, or a
  coordinator handoff where the firmware picks its own coordinator. In that
  case, re-plan the coordinator rule.
- Stopping a bystander group's coordinator doesn't silence its followers on
  this firmware.
- `_with_queue_resume` can't host the grouping step without changing its
  snapshot semantics for single-target calls.

**Acceptable variations**:
- Internal field names of `TargetPlan`, and the `GroupingError` message
  wording.
- Whether `play_file` delegates to `play_url`, as today, or shares a helper.

### Legs

> **Note:** These are tentative suggestions, not commitments. Legs are planned and created one at a time as the flight progresses. This list will evolve based on discoveries during implementation.

- [x] `01-target-group-engine`: pure planner (`targeting.py`), controller
  executor with poll-confirmation and `GroupingError`, and `speakers` +
  `detach` on `play_url` / `play_file` / `play_stream` / `say` (including
  the `"all"` sentinel and resume on `c0`), with tests and the docs for those
  tools. *High-risk tier (shared-interface break, state changes).*
- [x] `02-playlist-targeting-and-contract`: `playlist_play` and
  `playlist_from_page` target sets, the control-tool session-lookup
  fallback, the README system-prompt rewrite, CLAUDE.md, version 0.5.0, and
  the `targeting_smoke.py` apparatus. *High-risk tier (session keying).*
- [x] `04-coordinator-view-hardening`: *(added in flight, 2026-09-29)* The
  leg 03 run hit false `SoCoSlaveException`s on `c0` right after
  regrouping. The cause is SoCo caching a lagging bystander's topology view.
  This leg makes the last read come from `c0`'s own view and adds a
  resync-and-retry. It also hardens the apparatus and repairs spec step 7.
  *High-risk tier.*
- [ ] `03-hardware-targeting-verification`: behavior test
  `target-set-playback`, muted, on the operator's household.

---

## Post-Flight

### Completion Checklist
- [ ] All legs completed
- [ ] Code merged
- [ ] Tests passing
- [ ] Documentation updated

### Verification
- `.venv/bin/python -m pytest -q` passes, including `tests/test_targeting.py`
- `/mission-control:behavior-test target-set-playback` passes
- `grep -n "speaker: SpeakerName" mcp_sonos/server.py` shows only control
  tools, which stay single-speaker
- `mcp_sonos/__init__.py` is `0.5.0`
