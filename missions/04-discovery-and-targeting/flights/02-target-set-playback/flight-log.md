# Flight Log: Deterministic Target-Set Playback

**Flight**: [Deterministic Target-Set Playback](flight.md)

## Summary
Flight planned 2026-09-29, autonomously under the operator's
mission-wide authorization. Not yet executed.

---

## Leg Progress

### Leg 01: `target-group-engine`
**Status**: landed. Started/completed 2026-09-29 (single Developer session).

**Changes made**:
- `mcp_sonos/targeting.py` (new): pure, I/O-free planner. `GroupInfo`,
  `TargetPlan`, `plan_target_group(topology, targets, *, detach)`. Covers
  the exact-match fast path (detach=True), the four-rule coordinator
  precedence, the full "Detach algorithm" separate/join sequencing, and
  "Opt-out semantics" (single/same-group no-op, multi-group merge with
  followers-before-old-coordinator ordering). `_check_join_invariant`
  simulates the plan's own mutations and raises `AssertionError` if any
  `join` would ever target a UID still coordinating others — enforced
  internally, not just tested externally.
- `mcp_sonos/controller.py`:
  - `_group_member_uids_of` (UID-flavored sibling of `_group_members_of`,
    same guard pattern).
  - `_clear_socos_zgs_cache` extracted from `_invalidate_speakers` (same
    per-household clear, without zeroing the 30s discovery TTL) — used by
    `_plan_targets` and every confirmation/error read.
  - `GroupingError(RuntimeError)`, `TargetGroup` and `_TargetPlanContext`
    dataclasses.
  - `_snapshot_topology`, `_plan_targets` (read-only: resolve → dedupe →
    clear cache → snapshot → plan), `_execute_plan` (stop → unjoin → join
    → poll-confirm final membership, skipped when `plan.fast_path` → confirm
    no bystander is still `PLAYING`), `_confirm_final_membership`,
    `_confirm_bystanders_stopped`, `_grouping_error`.
  - `play_url`, `play_file`, `play_stream`, `say` rewired to
    `speakers: list[str]` + `detach: bool = True`. `play_url`/`say` run
    `_execute_plan` **inside** `_with_queue_resume`'s clip phase, so the
    native-queue snapshot still reads the chosen coordinator's pre-stop
    `PLAYING` state. `say`'s stale-coordinator retry re-resolves the
    planned coordinator by player name (not the caller's list). `say`'s
    `volume` applies to exactly `plan.final_members`. `say(["all"])` is
    unchanged (still `_say_all`); `"all"` mixed with names, or passed to
    any other tool, raises `ValueError`.
  - New response shape on all four: `targets`, `coordinator`,
    `group_members`, `stopped`, `detached`, replacing `requested` /
    `played_on_coordinator` / `spoken_on`. `say(["all"])` keeps its old
    shape (`spoken_on: "all"`, `coordinator_used`, `speakers`).
- `mcp_sonos/server.py`: `SpeakerTargets` (`list[str]`, `min_length=1`) and
  `DetachFlag` (`bool = True`) added to `play_url`, `play_file`,
  `play_stream`, `say`'s `speakers` param documents the `["all"]` sentinel
  and its exclusivity. Control tools untouched (still single-speaker
  `SpeakerName`).
- `tests/_fakes.py`: opt-in `FakeHousehold` (attach/group/do_join/
  do_unjoin/do_stop, full `_sync_groups` resync after every mutation — no
  stale `.group` ever). `SoCoFake.join`/`unjoin`/`stop` delegate to it when
  `.household` is set; unattached fakes keep the old simplistic behavior
  unchanged (verified: full pre-existing suite green before writing a
  single new test). `do_join` raises `AssertionError` if called on a UID
  still coordinating others — this is what makes controller tests enforce
  the executor invariant.
- `tests/test_targeting.py` (new, 19 tests): exhaustive planner coverage —
  fast path + idempotence, all four coordinator rules (including rule 2
  with c0's own group having bystanders), detach algorithm shapes (target
  follower of a bystander coordinator; non-c0 target coordinating 2+
  bystanders, delegated and left grouped), untouched groups, duplicates,
  all three opt-out shapes, and an adversarial battery proving the join
  invariant never fires `AssertionError`.
- `tests/test_target_group_controller.py` (new, 15 tests): execution
  order (stop before unjoin), zero calls to untouched groups, zero
  mutation calls on an unknown name, `GroupingError` on a mid-step
  exception (message contains the failing step + topology) and on a
  confirmation timeout (fake `time.monotonic` clock, `_sleep` patched to
  no-op — no real waiting), `GroupingError` on a bystander still
  `PLAYING` after separation, queue-snapshot-before-stop with resume
  landing on `c0` (rule 2, `c0`'s own group has a bystander), `say(["all"])`
  unchanged, `"all"` rejected (mixed with names, and by `play_url`/
  `play_stream`), `say` volume scoped to `final_members` in both
  directions (excludes a stopped bystander; includes a `detach=False`
  pulled-in non-target).
- Updated for the new signatures (no assertion weakened): `tests/
  test_queue_resume.py`, `tests/test_say_coordinator.py`,
  `tests/test_discovery.py`, `smoke_test.py` (`say` tool-call args only;
  not run).
- **One deliberate value change**, per the leg's own instruction:
  `tests/test_discovery.py::test_say_inline_retry_clears_socos_cache` now
  asserts `clear_cache_count == 2` (was 1) — `_plan_targets`'s new
  unconditional pre-snapshot clear plus the pre-existing stale-coordinator
  retry's clear. Kept the test's original intent distinct via a new
  `clear_count_at_failure` capture on the fake (`== 1` at the moment
  `play_uri` raises, proving the retry's own clear happens *after* the
  exception, not instead of the pre-snapshot one). This is a
  behavior-increase, not a loosening.
- `CLAUDE.md`: architecture note on `targeting.py`'s planner/executor
  split, the `_plan_targets`/`_execute_plan` split and why grouping runs
  inside `_with_queue_resume`'s clip phase, the three grouping invariants
  (never `join()` a still-coordinating speaker; a coordinator's `unjoin()`
  delegates rather than scattering; always clear the ZGS cache before a
  grouping-relevant topology read), a `detach` caveats bullet, and an
  "Important context" reminder to route topology *mutations* through
  `targeting.py` + `_plan_targets`/`_execute_plan`, not ad hoc join/unjoin.
- `README.md`: top overview table's TTS line + a new paragraph under
  "What it does" describing the `speakers`/`detach` contract and the new
  response keys. Did **not** touch the fenced "System prompt for your
  agent" block (`## Tools at your disposal` and its signature snippets) —
  that full rewrite is leg 02's explicit scope, per the Flight Director's
  instructions.

**Verification**:
- `timeout 180 .venv/bin/python -m pytest -q` → 152 passed (was 118 at
  leg start, +19 planner tests, +15 controller tests; zero hardware
  contact — no smoke script was run).
- `grep -n "speakers:" mcp_sonos/server.py` → exactly 4 matches
  (`play_url`, `play_stream`, `play_file`, `say`).
- `grep -n "speaker: SpeakerName" mcp_sonos/server.py` → only control
  tools + `now_playing`/`ungroup`/playlist control tools; no transport
  tool.
- `grep -n "def plan_target_group" mcp_sonos/targeting.py` found;
  `grep -n "import soco\|from soco" mcp_sonos/targeting.py` → empty
  (module stays a pure, cycle-free leaf).
- `.venv/bin/python -c "import mcp_sonos.server"` → imports cleanly.

**Deviations from the leg spec**: none. `fast_path` was defined as "the
plan issues zero stop/unjoin/join calls" (covers both the detach=True
exact-match case and the detach=False single-affected-group case) — an
internal-field-naming choice the flight's Adaptation Criteria explicitly
allows. `_execute_plan` takes `(ctx: _TargetPlanContext)` rather than a
bare `plan`, bundling `speakers_by_uid`/`c0`/`target_names`/`detach`
alongside it — same rationale (internal shape, not part of the leg's
observable contract).

No hangs; no hardware contact of any kind (no smoke script or
`discovery_smoke.py` invocation).

### Leg 02: `playlist-targeting-and-contract`
**Status**: landed. Started/completed 2026-09-29 (single Developer session).

**Changes made**:
- `mcp_sonos/playlists.py`: new private helper
  `PlaylistManager._session_for(speaker, coord)` — looks up
  `self._sessions[speaker.uid]`, falling back to
  `self._sessions[coord.uid]` when the first misses and `coord.uid !=
  speaker.uid`. `next_track`, `previous_track`, `stop`, and `status` all
  now call it instead of their own inline `self._sessions.get(speaker.uid)`
  — one helper backing all four call sites, per the leg's acceptance
  criteria. Docstring records the accepted limitation (fallback only
  recovers a session when the named speaker's *current* coordinator is
  `c0`).
- `mcp_sonos/controller.py`:
  - New `SonosController.playlist_play(speakers, name, *, shuffle=False,
    start_index=0, detach=True)`: calls `_plan_targets` then
    `_execute_plan` directly (no queue-resume wrapper — a playlist call
    always starts a NEW session, so there's nothing to snapshot), then
    `self.playlists.play(c0.player_name, name, shuffle=..., start_index=...)`.
    Returns the engine's own dict (`engine`, and per-engine `speaker`)
    merged with `targets`/`coordinator`/`group_members`/`stopped`/
    `detached`. Docstring explains why `speaker` (engine's own key) and
    `coordinator` (target-set key) end up holding the same value — both
    are kept rather than merged.
  - `playlist_from_page` signature changed from `speaker: str | None` to
    `speakers: list[str] | None = None` plus keyword-only `detach: bool =
    True`. When `speakers is not None`, it calls the new
    `self.playlist_play(...)` and merges the full result in (gaining
    `engine` + every target-set key); an explicit `speakers=[]` is NOT
    treated as omitted — it reaches `_plan_targets` via `playlist_play`
    and raises the same `ValueError` every other target-set tool raises
    for zero targets (the playlist is still built first; only the
    optional play step can fail this way). This was the leg's "Edge
    Cases" choice — documented in the method's docstring and in
    CLAUDE.md.
- `mcp_sonos/server.py`:
  - `playlist_play` tool: `speaker: SpeakerName` → `speakers:
    SpeakerTargets`, added `detach: DetachFlag = True`.
  - `playlist_from_page` tool: `speaker: str | None` → new
    `OptionalSpeakerTargets` annotated type (`list[str] | None`,
    `min_length=1` — so an explicit empty list is rejected at the tool
    boundary with a clean Pydantic error, verified live through the
    in-process `Client`), plus `detach: DetachFlag = True`.
  - `playlist_next`/`previous`/`stop`/`status` docstrings updated to note
    the any-member-of-the-group contract.
  - Control tools (`now_playing`, transport, volume, `reboot`, grouping,
    playlist `next`/`previous`/`stop`/`status`) are the only
    `speaker: SpeakerName` signatures remaining — verified by grep.
- `mcp_sonos/__init__.py`: `__version__` `0.4.0` → `0.5.0` (only
  occurrence in the tree — `grep -rn "0.4.0" mcp_sonos tests/*.py` is
  empty except one unrelated CIDR literal in `test_discovery.py`).
- `tests/test_version.py`: updated to assert `0.5.0`.
- `tests/test_playlist_session_fallback.py` (new, 5 tests): `_session_for`
  fallback via `FakeHousehold` — `stop`/`status`/`next_track`/
  `previous_track` all reach a `c0`-keyed worker session when a
  **follower** of `c0` is named, and a speaker in an **unrelated** group
  still takes the no-session path (session's `stop_event` observably
  untouched).
- `tests/test_playlist_targeting_controller.py` (new, 8 tests):
  `playlist_play` forms the group then plays on `c0` (target-set keys +
  engine's own `speaker`/`coordinator` both present and equal), stops and
  separates a bystander, `detach=False` keeps the existing group,
  `"all"` rejected, `shuffle`/`start_index` passthrough;
  `playlist_from_page` with `speakers=None` only builds, with `speakers=[
  ...]` plays through the same target-group path and gains the target
  keys, and `speakers=[]` raises after the playlist is already built.
- `targeting_smoke.py` (new, repo root): the flight's behavior-test
  apparatus. In-process FastMCP `Client` + `register_tools` for the two
  MCP-tool subcommands (`stream`, `say`); every other subcommand
  (`save-state`, `restore-state`, `mute-all`, `topology`, `group`,
  `stop-all`) reads/writes SoCo directly via the shared
  `SonosController`, since they need raw group-membership and
  volume/mute control that isn't (and shouldn't be) an agent-facing MCP
  tool. `group` and `restore-state` never call the MCP `group` tool
  (squawk 0006) — both unjoin every speaker they touch first so every
  subsequent `join()` targets an already-standalone speaker. No `clip`
  subcommand, per the leg-02 design review's reconciliation (already
  reflected in `tests/behavior/target-set-playback.md`, which needed NO
  changes — every subcommand name and flag the spec's step table uses
  matches the apparatus exactly, verified by re-reading the spec against
  the implemented CLI).
- `playlist_smoke.py`, `queue_smoke.py`, `reap_smoke.py`: `playlist_play`
  calls updated from `{"speaker": "Kitchen", ...}` /
  `{"speaker": SPEAKER, ...}` to `{"speakers": ["Kitchen"], ...}` /
  `{"speakers": [SPEAKER], ...}`. Arguments only — none of the three were
  run (hardware contact this leg is limited to `targeting_smoke.py
  topology`).
- `CLAUDE.md`: "Session keying" section gains a "Target sets (Flight 2)"
  subsection describing `playlist_play`'s group-then-play flow, the
  `_session_for` fallback, and the accepted limitation. The `detach`
  caveat bullet now lists `playlist_play`/`playlist_from_page` alongside
  the other four audio tools, plus a new caveat bullet for the
  `playlist_from_page(speakers=[])` rejection. `targeting_smoke.py`
  added to the Commands block. Removed the stale "35 tools" count per
  the leg's "remove numbers from prose" guidance (tool count drifts).
- `README.md`: "What it does" tool-taking-speakers paragraph now lists
  `playlist_play`/`playlist_from_page` alongside the other four; control-
  tool sentence notes the playlist session-lookup fallback.
  "System prompt for your agent" fully rewritten: tools list shows every
  audio tool's `speakers[]`/`detach?` signature plus `playlist_from_page`
  (previously missing from the prompt entirely); new numbered rule 2
  states the target-set/`detach` contract; "Play X everywhere" now says
  to pass every speaker in `speakers` and stops recommending
  `partymode` + `play_url`; auto-resume text now says resume only
  happens when the resulting coordinator was already leading its own
  group, and stopped bystanders/non-chosen targets' queues are never
  resumed; Error handling gained `NoSpeakersFound` and `GroupingError`
  guidance. Removed the "35 MCP tools" / "35 tools" counts (Architecture
  diagram and "What it does" header) per the same tool-count-drift
  guidance; reworded the Roadmap's speculative `play_radio(speaker, …)`
  to `play_radio(speakers, …)` since the flight was already touching
  that area.

**Verification**:
- `timeout 180 .venv/bin/python -m pytest -q` → 165 passed (was 152 at
  leg start: +5 session-fallback, +8 playlist-targeting-controller; zero
  hardware contact from the suite itself).
- `grep -n "speaker: SpeakerName" mcp_sonos/server.py` → only control
  tools (`now_playing`, `pause`/`resume`/`stop`/`next_track`/
  `previous_track`, `set_volume`/`mute`/`unmute`, `reboot`, `ungroup`,
  `playlist_next`/`previous`/`stop`/`status`). No transport or playlist
  tool that should be a target-set tool appears.
- `grep -n "play_url(speaker,\|play_file(speaker,\|play_stream(speaker,\|playlist_play(speaker,\|say(target" README.md`
  → empty (confirms no genuine stale singular signature remains). **Note
  on the leg's literal verification command** (without the trailing
  comma, e.g. `play_url(speaker` rather than `play_url(speaker,`): grep
  matches substrings, so `play_url(speaker` is also a substring of the
  now-correct `play_url(speakers[]...)` prose and the command is
  non-empty for that reason alone — every match it reports is a
  legitimate current signature, not a stale one. Verified by re-running
  with a comma-anchored pattern (empty) and by manual inspection of every
  matched line.
- `grep -rn "0.4.0" mcp_sonos tests/*.py` → empty except one unrelated
  CIDR literal (`10.0.4.0/24`) in `test_discovery.py`.
- `timeout 60 .venv/bin/python targeting_smoke.py topology` → exit 0,
  printed the live household's two groups (Fireplace Room coordinating
  Dining Room/Fireplace Room/Lounge/Patio, `STOPPED`; Kitchen standalone,
  `STOPPED`) with coordinator `state` and `uri` for each — the only
  hardware contact this leg made, read-only.
- `timeout 30 .venv/bin/python targeting_smoke.py --help` → lists all
  eight subcommands (`save-state`, `restore-state`, `mute-all`,
  `topology`, `group`, `stream`, `say`, `stop-all`).
- Ad hoc (not part of the persisted suite): two in-process `Client`
  smoke checks confirmed (a) `playlist_from_page(speakers=[])` is
  rejected by the real Pydantic tool boundary with a clean `ToolError`,
  and (b) `playlist_play(["Kitchen","Patio"], ...)` followed by
  `playlist_status("Patio")` (a follower) resolves through the fallback
  without error.

**Deviations from the leg spec**: none of substance.
- The `tests/behavior/target-set-playback.md` apparatus flags already
  matched exactly (no `clip` subcommand, matching subcommand/flag names)
  — the file needed no edits this leg; the design review's reconciliation
  note from the prior session already covered it.
- The leg's literal `grep` verification command for stale README
  signatures is a substring match that also matches the correct plural
  `speakers[]` form — see the Verification section above. No content
  change was warranted; this is a note about the grep pattern, not a
  finding.

---

## Flight Director Notes

### 2026-09-29: Planning probes (ground truth for the design decisions)
- **Muted stream premise.** `play_stream("Kitchen",
  "http://ice1.somafm.com/groovesalad-128-mp3")` reached `PLAYING` via the
  radio scheme in 6.3 s. `now_playing` showed the
  `x-rincon-mp3radio://` URI. Kitchen's mute and the household grouping were
  restored exactly.
- **Regroup burst (contention probe, from the Flight 1 debrief).** Four
  iterations of Patio and Dining Room leaving Fireplace's group and joining
  Kitchen, then being restored:

  | Measure | Result |
  |---|---|
  | Commands | 0.75–1.10 s |
  | Settle (polling with `clear_cache`) | 0.16–0.32 s |
  | Anomalies under a concurrent 20 Hz TCP 1400 probe of all 5 speakers | **0** |

  All speakers were muted during the probe and restored afterwards; the
  topology was restored exactly.
- **Observability finding.** Before the probe, the followers Dining Room,
  Lounge and Patio reported `PLAYING` while their coordinator, Fireplace
  Room, reported `STOPPED`. Follower transport state is unreliable, so every
  assertion reads state through the coordinator.
- **Sixth audio path found.** `playlist_from_page(..., speaker=...)` starts
  playback, so it is included in scope as an audio-sending tool.
- **Planning mode.** This is an autonomous run: the Flight Director resolved
  the interview phases by taking the recommended options and recording their
  rationale in the design decisions. Operator overrides are welcome at PR
  review.
- Branch `flight/02-target-set-playback` is stacked on
  `flight/01-zero-config-discovery`, because PR #11 is not yet merged.

### 2026-09-29: Design review, cycle 1 (Architect)
- Verdict: approve with changes. Baseline: 118 passed.
- **[high] Fixed.** The initial topology snapshot was not declared to bypass
  SoCo's 5 s cache, so a stale plan could leave a bystander playing. The
  design now clears the cache per household, unconditionally, before every
  snapshot.
- **[high] Fixed.** The opt-out merge can't use `join()` once per target:
  SoCo's `join` moves only the speaker it is called on (verified in
  `soco/core.py`; `partymode()` itself joins each zone). The merge now joins
  **every member** of each merged group individually. Non-target members of
  merged groups are explicitly pulled in, which answers the Architect's
  question.
- **[medium] Fixed.** Coordinator choice could drop a *target's* playing
  queue. Added a precedence rule: prefer the first target that is a
  `PLAYING` coordinator. The planner input now includes each coordinator's
  transport state.
- **[medium] Fixed.** The apparatus restore algorithm is now specified:
  unjoin everything, `group()` each saved group of two or more, then restore
  volume and mute.
- **Suggestion adopted.** Extend `SoCoFake.join`/`unjoin` to real
  single-speaker semantics before writing the merge and detach tests.
- The changes were substantive (algorithm and coordinator rule), so a second
  review cycle was spawned.

### 2026-09-29: Hardware probe of grouping semantics, and design review cycle 2 (Architect)
- **Probe** (muted, state restored exactly):
  - A: Fireplace, coordinating 4, called `unjoin()`. Its followers **stayed
    grouped** under a firmware-elected Lounge.
  - B: Fireplace, coordinating 4, called `join(Kitchen)`. It **did not
    join**: coordination moved to Dining Room and Fireplace stayed in the
    old group.
  - This produced a new design decision, "Firmware grouping semantics", and
    an executor invariant: never `join()` a speaker that coordinates
    others.
- **Cycle-2 verdict:** approve with changes. The Architect walked five
  topology cases, and all reach the intended end state.
  - **[high] Fixed.** Stop-first ran before the queue snapshot. The design
    now splits `_plan_targets` (read-only, before the snapshot) from
    `_execute_plan` (inside the resume's clip phase).
  - **[medium] Fixed.** "Members become standalone" was wrong; the design
    now says they are delegated, as the probe confirmed. The fake models
    delegation, and a new unit test plus a new behavior-test step 7 cover
    a target coordinating three bystanders. The behavior-test steps were
    renumbered to 12.
  - **[medium] Fixed.** Confirmation now re-reads each bystander's
    coordinator state and raises if any is `PLAYING`.
  - **[low] Fixed.** The order of the "Separate" steps is now explicit.
  - **Questions answered in the spec:** `say`'s retry re-resolves `c0` by
    name, and the playlist/stream plan-then-execute asymmetry is
    intentional.
- **Two cycles reached (the maximum).** The cycle-2 findings are resolved in
  the spec, and the remaining risk is concentrated in executor details.
  Those get a per-leg Developer design review, since leg 01 is high-risk,
  and the muted hardware behavior test. I am proceeding without escalating,
  under the autonomous authorization, and flagging this for operator
  attention in the PR.
- The apparatus `group` and `restore` now use standalone-then-join instead
  of the existing `group` tool. That tool has the join-a-coordinator defect,
  logged as **squawk 0006** (routine, out of flight scope).
- Flight marked `ready` under the autonomous authorization.

### 2026-09-29: Execution start
- Flight marked `in-flight`. The phase file `leg-execution.md` is loaded and
  valid.
- **Leg 01 `target-group-engine`: tiered HIGH-RISK.** It is a breaking
  change to a shared interface (four tool schemas), and it changes state:
  topology mutations, the stop-first behavior, and the resume ordering. A
  Developer design review follows.

### 2026-09-29: Leg 01 design review, cycle 1 (Developer)
- Verdict: approve with changes. The consumer grep is complete, and the
  opt-in `FakeHousehold` is safe, because no existing test exercises the
  group tools.
- **[high] Fixed.** For `detach=False`, the confirmation compared `c0`'s
  group to the *target set*. The merged group legitimately includes
  pulled-in non-targets, so it would always time out. Added a required
  `TargetPlan.final_members` field, and confirmation now compares against
  it, matching the flight's "planned membership".
- **[medium] Fixed.** `test_discovery.py::test_say_inline_retry_clears_socos_cache`
  expects exactly one clear; `_plan_targets` adds another. The leg now says
  to update the exact count and keep the test's intent.
- **[medium] Resolved by hardware.** The review worried that the
  followers-first merge mechanism had never been checked on hardware. I ran
  a muted probe, 3 of 3 trials: the old coordinator is standalone after its
  followers `join(c0)`, and its own `join(c0)` settles in 0.15 s. State was
  restored exactly.
- **Suggestions and questions adopted.** The fake removes a moving follower
  from its old group. `say` volume applies to `final_members`, which
  includes pulled-in members and excludes stopped bystanders.
- The changes were a precision field and test notes, and the one unverified
  assumption is now verified on hardware, so there was no second cycle. Leg
  marked `ready`. [HANDOFF:review-needed]

### 2026-09-29: Leg 01 [LAND:leg] received; leg 02 designed
- The Flight Director re-ran the suite and got **152 passed** (2.36 s),
  matching the Developer's report.
- **Leg 02 `playlist-targeting-and-contract`: tiered HIGH-RISK.** It
  changes worker-session lookup for the control tools, where session
  keying is a CLAUDE.md invariant. It also breaks the `playlist_play` and
  `playlist_from_page` schemas. A Developer design review follows.

### 2026-09-29: Leg 02 design review, cycle 1 (Developer)
- Verdict: approve with changes. The baseline was 152 passed, and the
  citations are accurate.
- **[medium] Fixed.**
  - The version grep is now scoped to `tests/*.py`, because historical run
    logs legitimately mention 0.4.0.
  - The README stale-signature grep now covers every audio tool.
- **[medium] Reconciled.** The flight design listed a `clip` subcommand in
  the apparatus. I am **dropping** it: no behavior-test step uses it, and
  the `say` steps already exercise the blocking-clip path through
  `_with_queue_resume`. The flight's apparatus decision is superseded by
  this note; the original text is kept.
- **[medium] Documented.** If `c0` is later made a follower elsewhere, the
  session fallback misses. This is recorded as an accepted best-effort
  limitation in the CLAUDE.md caveats. Worker takeover detection usually
  ends such a session within one poll.
- **Adopted:**
  - a `previous_track` fallback test
  - `playlist_from_page` added to the system prompt
  - a docstring note on the duplicate `speaker`/`coordinator` keys
  - the apparatus passes `--speakers` through unchanged, with no special
    handling of `"all"`
  - `restore-state` reports a live re-read of each speaker
- These were precision edits only, so no second cycle. Leg marked `ready`.
  [HANDOFF:review-needed]

### 2026-09-29: Flight review — Reviewer [HANDOFF:confirmed] for legs 01–02 (165 passed; planner join-invariant and snapshot-before-stop ordering traced; no weakened assertions). Two non-blocking notes accepted as-is: unchecked criteria boxes pending leg 03; `targeting_smoke.py` forward-ref `SoCo` annotation (harmless under `from __future__ import annotations`). Legs 01–02 → completed; leg 03 (hardware behavior test) pending.
