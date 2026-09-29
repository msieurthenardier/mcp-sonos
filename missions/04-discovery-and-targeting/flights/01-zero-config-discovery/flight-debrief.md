# Flight Debrief: Zero-Config Discovery

**Date**: 2026-09-29
**Flight**: [Zero-Config Discovery](flight.md)
**Status**: landed
**Duration**: 2026-09-28 to 2026-09-29, a single autonomous session
**Legs Completed**: 3 of 3 (leg 02 was added in flight)
**Plugin version**: 1.1.0

## Outcome Assessment

### Objectives Achieved
Discovery now works with zero configuration on the operator's LAN. It runs
four stages:
1. Configured `SONOS_IPS` seeds. They are now ways into the household, not
   an exhaustive list.
2. Learned seeds: the IPs from the last successful discovery, kept in
   process.
3. A bounded, rate-limited subnet scan, which `SONOS_SCAN_NETWORKS` can
   override.
4. SSDP, as a last resort.

When every stage is empty, the server raises `NoSpeakersFound`, which lists
what was tried and what to set. Forced refreshes bypass SoCo's 5 s topology
cache through `_invalidate_speakers()`. Tool descriptions, README,
`.env.example`, CLAUDE.md and the smoke scripts are aligned, and the version is
0.4.0.

Behavior test `zero-config-discovery` **passed 8/8** on real hardware
([run log](../../../../tests/behavior/zero-config-discovery/runs/2026-09-29-02-27-28.md)).
Patio, which the old pinned list hid, is now discovered in every
configuration.

### Mission Criteria Advanced
- With zero configuration, all five speakers are found across repeated runs.
  This is behavior-test backed.
- Configured IPs work as a way in without hiding unlisted speakers. This is
  behavior-test backed.
- There is a diagnostic error when nothing is found.
- The discovery half of the docs criterion.
- The discovery half of the unit-test criterion.

The targeting half of the docs and unit-test criteria belongs to Flight 2.

## What Went Well
- **Design review caught the SoCo 5 s `ZoneGroupState` cache before any code
  or hardware contact.** Cycle-1 Architect found it by reading the SoCo source.
  Without it, the name-miss retry and `refresh_speakers` would have silently
  served stale topology. Cycle 2 then caught the second retry call site in
  `say` and the missing attributes on the shared test fake.
- **The flight's adaptation criteria worked as intended.** The
  post-landing hardware check found the scan disruption. The pre-declared
  "divert if scan proves unreliable" trigger produced a scoped new leg (02):
  - Leg 01 stayed immutable.
  - The design-decision amendment was appended, preserving the original text.
  - The behavior-test timing was revised with a note.
  - The hardware leg was renumbered.
  The audit trail is complete.
- **The Flight Director's own post-`[LAND:leg]` hardware re-check.** The
  Developer's single permitted smoke run passed, but it came in at 4.08 s.
  Re-running as three fresh processes exposed an `Errno 101` failure, and
  targeted probes isolated the cause to the ARP burst:

  | Test | Result |
  |---|---|
  | No scan, 100 sequential connects | 100/100 clean |
  | After a scan at 256 threads | anomalies in 2 of 3 trials |
  | After a scan at 32 threads | anomalies in 0 of 2 trials |

  A single green run would have shipped the defect.
- **Injectable stage seams.** `_probe_port`, `_expand_seed`, `_scan`, `_ssdp`
  and the adapter lookup made a 40-test, hardware-free suite possible. It
  mirrors the project's existing DI philosophy.
- **The observability premise was verified at planning.** FastMCP forwards
  exception text word for word, so no test-only seam was needed. Behavior-test
  step 7 asserted on the real diagnostic text.

## What Could Be Improved

### Process
- **Planning probed the scan in isolation, not under contention.** The
  prerequisite asked "does the scan find the speakers", which it did 5/5, but
  not "does the scan disturb other traffic". On a WSL2 mirrored-networking
  host that CLAUDE.md already flags as fragile, an operation that bursts
  network traffic deserved a contention probe. Cost: one added leg, with two
  Developer spawns and one design review.

### Technical
- **Configured seeds are re-probed ahead of learned seeds on every
  discovery.** A stale `SONOS_IPS` entry costs about 1 s per dead entry per
  refresh; behavior-test step 6 took 2.24 s. Each decision was sound alone
  ("configured intent wins", "gate before expand"), but the combination costs
  time. Needs a design call on precedence, so it is a recommendation, not a
  squawk.
- **Module-level `_learned_seed_ips` in `speakers.py` breaks the rule that
  cache state lives on the controller.** It is safe under stdio and
  single-request handling. The assumption is stated in a code comment but not
  enforced or named in CLAUDE.md. It needs an autouse reset fixture in tests.
- **`_speaker_dict` makes UPnP calls per speaker.** One speaker's transient
  failure fails the whole `list_speakers`. This predates the flight, and the
  flight saw it once in the wild. Squawk candidate.

### Test metrics
| | Mission 03 seed | Now |
|---|---|---|
| Tests | 78 | **118** |
| Pass / fail / skip | 78 / 0 / 0 | 118 / 0 / 0 |
| Full-suite wall-clock | 1.38–1.47 s (4 runs) | 1.85–1.95 s (4 runs) |
| Flakes | none | none |

- All 40 new tests are in `tests/test_discovery.py` (0.64 s).
- The files with prior per-file baselines are unchanged:
  `test_queue_resume.py` went from 0.66 s to 0.68 s, and `test_queue_path.py`
  from 0.21 s to 0.23 s.
- The +34 % wall-clock is proportional to the +51 % test count, not a slowdown
  of existing tests.
- `pytest-randomly` is still not installed, so order-independence is
  unverified. Same caveat as the prior debrief.

### Documentation
- Complete for the feature. It was verified by the flight review and by the
  debrief's grep checks.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| Leg 02 added in flight (learned seeds + `max_threads=32`) | The full-speed scan made connections to real speakers fail for 1–3 s afterwards | Yes: use the adaptation criteria and a new leg, and never reopen a landed leg |
| Behavior-test timing split into a cold first call and later calls | Learned seeds changed the cost model | Yes: revise the spec deliberately, with a dated note |
| `ifaddr` added to `pyproject.toml` | It became a direct import | Yes: declare direct imports even when a dependency already pulls them in |
| Validator's spec-readability note applied (step 6 has no timing bound on purpose) | A reader could take the omission for an oversight | Yes |

## Key Learnings
- **Probe the effect on the environment, not just the function.** Any
  operation that bursts network traffic (a scan, fan-out UPnP calls, a regroup
  across several speakers) needs a "what does this do to other traffic" probe
  at planning. This applies directly to Flight 2's regrouping sequence.
- **Library caches below ours are part of the freshness contract.** Any
  forced refresh must clear SoCo's 5 s `ZoneGroupState` cache, and so must any
  read-after-write within one tool call, such as Flight 2's regrouping.
- **The Flight Director should re-verify on hardware after a Developer's
  green run.** The first reading here (4.08 s) was the clue.

## Methodology Observations

1. **Flight-planning premise probes don't prompt for side-effects under
   contention.**
   - *Skill/phase*: flight, Phase 4 (premise audit).
   - *What happened*: The flight skill's premise-audit guidance asks whether
     the apparatus can *act* and *observe*. The discovery DD's empirical
     premise ("the bounded scan is reliable") was probed for correctness only.
     Its side-effect on concurrent traffic went unasked until after landing.
   - *Expected*: The premise audit prompts for a third axis for operations
     that are bursty or shared-resource: "does the action disturb its
     environment or other consumers?"
   - *Cost*: One added leg (Developer design review, Developer implement), a
     spec timing revision, and a renumbering.
   - *Plugin version*: 1.1.0.
2. **Agentic-workflow gives no guidance on Flight Director verification
   between `[LAND:leg]` and the flight review.**
   - *Skill/phase*: agentic-workflow, 2c.
   - *What happened*: The Developer's single permitted hardware run passed.
     Only the Flight Director's own ad-hoc repeated runs exposed the
     intermittent failure.
   - *Expected*: For legs with real-environment effects, 2c suggests a
     Flight Director-side repeated spot check (N fresh runs) before
     proceeding, since single green runs hide intermittency.
   - *Cost*: None this time, because the Flight Director did it unprompted.
     Without it, the defect would have reached the behavior test, or the
     operator.
   - *Plugin version*: 1.1.0.

## Recommendations
1. **Flight 2 planning** must decide explicitly:
   - ZGS-cache invalidation between regroup steps.
   - Partial-failure semantics that reuse the `NoSpeakersFound(RuntimeError)`
     / `SpeakerNotFound(ValueError)` taxonomy.
   - A contention probe of the regroup burst on hardware.
   - That any new shared state has a declared owner.
2. **Revisit configured-seed vs learned-seed precedence.** Try learned seeds
   first, or demote configured seeds that fail repeatedly. This is design
   work for a future flight or maintenance cycle.
3. **Name the learned-seed global** in CLAUDE.md, along with its
   single-request assumption, as a second, deliberate state-ownership pattern.
   Alternatively, fold it into the controller. *(Squawk.)*
4. **Make `list_speakers` tolerate one speaker's transient UPnP failure**
   instead of failing wholesale. *(Squawk.)*

## Action Items
- [ ] Squawk [0004](../../../../squawks/0004-list-speakers-fails-wholesale.md): `list_speakers` fails wholesale when one speaker's
  `_speaker_dict` UPnP call fails (defect, routine)
- [ ] Squawk [0005](../../../../squawks/0005-claude-md-learned-seed-state.md): CLAUDE.md doesn't name the `_learned_seed_ips` module-level
  state or its single-request assumption (servicing, routine)
- [ ] Future design: seed-precedence and dead-configured-seed cost
  (recommendation 2)
- [ ] Operator: merge PR #11
