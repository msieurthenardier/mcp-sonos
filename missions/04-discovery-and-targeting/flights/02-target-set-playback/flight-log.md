# Flight Log: Deterministic Target-Set Playback

**Flight**: [Deterministic Target-Set Playback](flight.md)

## Summary
Flight planned 2026-09-29, autonomously under the operator's
mission-wide authorization. Not yet executed.

---

## Leg Progress

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
