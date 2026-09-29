# Mission Debrief: Zero-Config Discovery & Deterministic Speaker Targeting

**Date**: 2026-09-29
**Mission**: [Zero-Config Discovery & Deterministic Speaker Targeting](mission.md)
**Status**: completed
**Flights**: 2 of 2 completed
- [Zero-Config Discovery](flights/01-zero-config-discovery/flight-debrief.md)
- [Deterministic Target-Set Playback](flights/02-target-set-playback/flight-debrief.md)

**Duration**: 2026-09-28 to 2026-09-29. Planned with the operator, then
executed autonomously under the operator's instruction to "run the mission
autonomously".
**Plugin version**: 1.1.0

## Outcome Assessment

The mission's outcome is achieved. An agent can drive the whole household
with **no IP configuration**, and "play this on Kitchen and Patio" plays on
**exactly** Kitchen and Patio, in one call, however the household was grouped
beforehand. Both halves are verified on the operator's real hardware by
behavior tests:
- `zero-config-discovery`: 8/8
- `target-set-playback`: 12/12, run muted, with the household restored
  exactly

### Success Criteria

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Zero-config discovery finds all five speakers, repeatedly | **Met** | `zero-config-discovery` run, steps 2–3: 3 fresh processes, 5/5 speakers each |
| 2 | Configured IPs are a way in and don't hide unlisted members | **Met** | Same run, steps 4–6, plus `test_discovery.py` |
| 3 | Diagnostic error when nothing is found | **Met** | Same run, step 7: `NoSpeakersFound` names each stage and the environment-variable hints |
| 4 | Every audio tool accepts a target set | **Met** | All six tools take `speakers` |
| 5 | Default plays on exactly the target set | **Met** | `target-set-playback` step 3, plus the 19 planner tests |
| 6 | Bystanders are stopped and separated | **Met** | Steps 3, 6 and 7. Step 6 failed first and passed after leg 04. |
| 7 | Untouched groups stay untouched | **Met** | Step 5 in both runs, plus "zero calls" unit tests |
| 8 | Opt-out gives today's behavior | **Met** | Steps 2 and 8, plus unit tests for all opt-out shapes |
| 9 | Say-all broadcast is preserved | **Met** | Steps 10 and 11 |
| 10 | Schemas, README and CLAUDE.md are accurate | **Partially met** | Targeting and discovery docs are accurate. Squawk 0005 is still open: CLAUDE.md doesn't name the learned-seed module state as a deliberate exception to "the controller owns caches". |
| 11 | Unit suite covers both halves without hardware, and passes | **Met** | 78 → 118 → 172 tests, all green, 0 flakes |

The mission achieved 10 of 11 criteria fully and 1 partially. The partial
item is a known, doc-only squawk.

## Flight Analysis

**Flight 1, Zero-Config Discovery** (4 → 3 legs, completed)
- **Result:** a four-stage discovery pipeline (configured seeds → learned
  seeds → a rate-limited `/24` scan → SSDP), with `NoSpeakersFound`
  diagnostics and SoCo cache invalidation on every forced refresh. Version
  0.4.0.
- **Challenge:** after landing, the Flight Director re-checked on hardware
  and found that a full-speed 256-thread scan disrupted LAN connections for
  1–3 s. This triggered a pre-declared adaptation criterion, which added
  leg 02 (learned seeds and a 32-thread scan).

**Flight 2, Deterministic Target-Set Playback** (3 → 4 legs, completed)
- **Result:** a pure planner (`targeting.py`) and a thin executor. It is
  built on hardware-verified firmware semantics: a coordinator's `unjoin`
  delegates its followers, and joining a coordinator that still has
  followers is unreliable. Every audio tool takes `speakers` + `detach`, the
  README system prompt was rewritten, and the version is 0.5.0.
- **Challenge:** the first hardware run passed 9/12.
  - It found a false `SoCoSlaveException` after regrouping: SoCo cached a
    lagging bystander's topology view. Leg 04 was added to fix it.
  - It also found a spec setup defect and an apparatus flake.
  - The re-run passed 12/12.

**Common pattern across both flights:** each had its planning probes pass,
and then **a real-environment side effect** that nobody probed forced one
added leg. Both were caught by the Flight Director's hardware verification,
never by unit tests.

## Process Analysis

### Planning effectiveness
- The flight boundary held. Discovery landed first so that targeting's
  hardware verification could see Patio.
- Both flights grew by exactly one leg. The flight/leg hierarchy absorbed
  this cleanly: landed legs stayed immutable, design-decision amendments
  were appended, and specs were revised with dated notes.
- Design review was intensive and productive. Flight 2 used both
  flight-level Architect cycles and three leg-level Developer reviews, and
  caught several real algorithm bugs before any code existed. It still
  missed the library-cache read-order defect, because no review looked at
  *whose view* a shared cache held.

### Execution patterns
- **What worked:**
  - Flight Director-side hardware re-verification after a Developer's green
    run. This caught the Flight 1 scan disruption.
  - Muted behavior tests with a live-verified safety gate, and an
    independent Flight Director check before any unmute.
  - The Validator tracing code on its own to separate spec defects from
    product defects.
  - Pipelined judging on the re-run.
- **Friction:**
  - Apparatus defects looked like product failures twice: `stop-all`
    swallowing errors, and the `restore-state` report reading a lagging
    view.
  - The behavior-test protocol has no notion of an apparatus fault.

### Autonomous orchestration
- The operator approved the mission and Flight 1, then said "run the
  mission autonomously". Flight 2's interview decisions were made by the
  Flight Director and recorded with rationale in `flight.md`, and flagged
  for operator override at PR review.
- Where methodology gates called for a human (the design-review cycle cap,
  the behavior-test fail decisions, flight completion), the Flight Director
  made the call and logged it. Nothing irreversible was done without a
  record.
- The agent never merged a PR. The PRs are stacked, #12 on top of #11, for
  the operator.

## Knowledge Capture

### Technical lessons
- **On this host, speakers need gentle handling.** A full-speed subnet scan
  disrupts ARP. Follower transport state is unreliable. Each speaker's
  topology view is eventually consistent. SoCo caches the last-polled
  speaker's view per household for 5 s. All four are now written into
  CLAUDE.md.
- **Plan/execute split with a pure planner** is the house pattern for any
  multi-object mutation, used in both flights. Consider adding a replayed
  invariant check like `_check_join_invariant`.
- **`FakeHousehold` lag mode** is the template for testing eventually
  consistent distributed state without hardware.

### Process lessons
- **Probe the environment's reaction and the client library's caching, not
  only the function's correctness.** This recurred in both flights; see the
  methodology findings.
- **Author behavior-test setups against the system's own decision rules.**
  Step 7's setup triggered the wrong coordinator rule.
- **Keep apparatus code at the product's standard.** It swallowed errors
  and lacked the sync discipline the product has.

### Documentation updates
- CLAUDE.md now covers:
  - discovery: the four stages, learned seeds, and the rate-limited scan
  - grouping: the join invariant, per-speaker views, `_sync_view`, the
    `detach` semantics, and session fallback
- The README configuration table and the system prompt are rewritten.
- **Outstanding:** squawk 0005 (naming the learned-seed state in CLAUDE.md).

## Technical Debt and Follow-Ups

| Priority | Item | Vehicle |
|---|---|---|
| High | Control and transport tools (`pause`/`resume`/`stop`/`next`/`previous`/volume/mute) don't use `_sync_view`. They are exposed to false `SoCoSlaveException` within about 5 s of a target-set regroup, which is now the primary regroup path. | Next mission, a hardening flight |
| High | Two stale-coordinator strategies (`with_stale_coord_retry`, and `_sync_view`/`_on_coordinator`) are both still gaining call sites. Unify them. | Same flight |
| Medium | Squawk 0006: the legacy `group` tool can silently fail to join a coordinating speaker. | Squawk turnaround |
| Medium | Squawk 0004: `list_speakers` fails wholesale on one speaker's transient error. | Squawk turnaround |
| Low | Squawks 0005 (doc) and 0007 (apparatus restore report). | Squawk turnaround |
| Low | Configured seeds are re-probed before learned seeds, costing about 1 s per dead `SONOS_IPS` entry per refresh. | Design call, next mission |
| Low | `say()` under lag mode is untested. The `_say_all` Fireplace-Room URI oddity is unexplained. `pytest-randomly` is still not installed; this is the third mention across debriefs. | Next mission or maintenance |

## Methodology Findings (Triage)

| # | Finding | Destination | Flights / recurrence |
|---|---|---|---|
| 1 | **The premise audit misses environmental side effects and client-library cache consistency.** Premise probes check that an operation *works*, not what it does to its environment. Flight 1 missed the scan's ARP disruption; Flight 2 missed which node's view SoCo's shared cache held before a coordinator-only call. Each cost one added leg, and in Flight 2 also a second full hardware behavior-test run. | **Methodology observation**: flight, Phase 4 premise audit; agentic-workflow 2a cache-freshness risk check | F01 observation 1 and F02 observation 1. **Occurred twice in this mission** (count once across both flights). |
| 2 | **The behavior-test run skill doesn't distinguish apparatus faults from system faults, and forbids pipelined judging.** Two FAIL verdicts were apparatus-caused, and a rerun-checkpoint was needed. The Flight Director deviated from "judge before advancing" for wall-clock reasons, safely, because per-command evidence was complete. | **Methodology observation**: behavior-test Phase 4 | F02 observation 2. Once. |
| 3 | **Agentic-workflow gives no Flight Director-side verification step between `[LAND:leg]` and the flight review** for legs with real-environment effects. The Flight Director's own repeated runs caught Flight 1's intermittent disruption, where the Developer's single run was green. | **Methodology observation**: agentic-workflow 2c | F01 observation 2. Once, but the no-cost outcome depended on Flight Director initiative. |
| 4 | **The interaction between escalation gates and explicit autonomous-run authorization is unspecified.** This covers the design-review cap, the behavior-test fail decisions and flight completion. | **Local lesson**, with no cost observed. Record the operator's standing authorization in the flight log whenever it is used. | F02 observation 3 |
| 5 | Apparatus scripts were written to a lower standard than the product, swallowing errors and lacking sync discipline. | **Local lesson** for this project: hold behavior-test apparatus to product review standards | F02 |

Nothing is reported upstream from this debrief. Findings 1–3 are recorded
for a later `/mission-control:service-report` sweep. **Finding 1 has now
recurred twice within one mission under the same plugin version**, which
makes it the strongest candidate.

## Top 3 Went Well
1. **Both outcomes were verified on real hardware with independent witnesses.**
   The runs scored 8/8 and 12/12, and the household was never audible and
   always restored.
2. **Pure planners with injectable seams.** Discovery stages and the
   targeting planner needed zero logic rework, and every defect was found in
   the I/O layer.
3. **Adaptive planning without losing the audit trail.** Two in-flight legs
   were added through pre-declared adaptation criteria. Legs stayed
   immutable, design decisions were amended in place, and specs were revised
   with dated notes.

## Top 3 To Improve
1. **Probe side effects and library caching at planning.** That would have
   avoided both added legs.
2. **Harden the control tools against view lag, and unify the retry
   strategies**, before more call sites accrete.
3. **Hold apparatus code to product standards.** Two false FAILs came from
   the test scripts.
