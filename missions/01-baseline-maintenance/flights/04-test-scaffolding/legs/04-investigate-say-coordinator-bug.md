# Leg: 04-investigate-say-coordinator-bug

**Status**: completed
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Investigate and ideally fix the mission's only remaining real bug: `smoke_test.py` `say()` fails with `play_uri can only be called/used on the coordinator in a group` even when `list_groups` reports the target speaker (e.g. Kitchen) as its own singleton coordinator. The bug has been observed in 2 of 3 prior debrief smoke runs (Flight 01 and 03 debriefs) and is captured in mission Known Issues. Write a failing SoCoFake-driven pytest test that reproduces the bug; fix the root cause if it's small and obvious; otherwise mark `xfail` with a clear follow-up note.

## Context
- **Bug location**: `mcp_sonos/controller.py:328` (approximate; may have drifted) — `coord.play_uri(url, title=f"Say: {text[:40]}")` raises `play_uri can only be called/used on the coordinator in a group` (SoCo's `SoCoSlaveException` family).
- **Pre-debrief hypothesis** (Flight 02 debrief): Sonos household topology — coordinator changed between flight execution and debrief. **REFUTED** in Flight 03 debrief: smoke confirmed via `list_groups` that the target speaker IS its own singleton coordinator at call time. The bug is reproducible against a "should-be-coordinator" target.
- **Architect's candidate root causes** (Flight 01 debrief Anomaly Investigation):
  1. Cached SoCo for "Kitchen" has stale `is_coordinator` after a recent topology change; SoCo's `group.coordinator` view diverged from firmware reality.
  2. `_resolve_coordinator` returns the speaker itself in the `coordinator=None` lull (per `_coordinator_of` design), but Sonos rejects `play_uri` on a non-coordinator even when SoCo's view says otherwise.
- **Scope guard** (flight design decision, refined at design review): the signal is **surface area**, NOT line count. **Proceed with fix** if the change is contained to `controller.py`'s coordinator-resolution surface — specifically `_coordinator_of`, `_resolve_coordinator`, `say()`, OR `_speakers_fresh`'s cache-invalidation policy (e.g. forcing a re-discovery before `say()` calls `play_uri`). **Switch to xfail** if the fix requires changes to `playlists.py` worker, modifications to SoCo library internals, adding a NEW cache layer beyond `_speakers_fresh`, or cross-module reconciliation. The leg's success criterion is "regression test scaffolding exists for this bug," NOT "the bug is fixed." Hard line-count thresholds aren't used — judge by what files/symbols the diff touches.

## Inputs
- `mcp_sonos/controller.py` — `say()` method, `_resolve_coordinator`, `_coordinator_of`
- `mcp_sonos/playlists.py` worker — references similar coordinator-resolution patterns
- `tests/_fakes.py::SoCoFake` — extended in this leg if needed to model the stale-coordinator state
- Mission Known Issues entry — to be updated with findings

## Outputs
- A pytest test (`tests/test_say_coordinator.py` or extension of an existing test file) that reproduces the bug deterministically against `SoCoFake`
- One of two outcomes:
  - **Fix outcome**: bug fixed in `controller.py`; smoke `say()` passes; test passes; mission Known Issue resolved
  - **`xfail` outcome**: test marked `pytest.mark.xfail(reason="...")` with detailed comment pointing at mission Known Issue; bug not fixed in this flight; mission Known Issue updated with investigation findings and concrete next-step recommendation

## Acceptance Criteria
- [x] A pytest test reproduces the `play_uri can only be called/used on the coordinator in a group` error (or equivalent) against `SoCoFake` deterministically — runs in CI/local without needing live hardware to fail
- [x] If the root cause is fixable within the surface guard (`controller.py` coordinator-resolution surface): fix is implemented; test passes; mission Known Issues entry updated to "resolved by Flight 04 Leg 04 commit `<hash>`" — **FIX outcome chosen**; mission Known Issue marked resolved (commit hash will be filled at Phase 2d landing)
- [x] **Live-hardware smoke verification of `say()` fix is conditional**: if Sonos hardware is reachable from the executing environment, re-run `smoke_test.py` and confirm `say()` passes. If hardware is unreachable, document in the flight log and rely on the SoCoFake test as the regression net — **smoke scripts found broken by an unrelated Leg 02 regression; verification deferred and the regression captured as a new mission Known Issue**
- [x] If the root cause requires out-of-scope work: test is `pytest.mark.xfail(reason="...")` with a clear pointer to the mission Known Issue; mission Known Issue entry updated with the four-point structure: (a) confirmed hypothesis, (b) observed divergence, (c) concrete fix-shape sketch, (d) which surface-guard rule triggered the deferral — **N/A: FIX outcome, not xfail**
- [x] The "fix or xfail" decision is documented in the flight log under Decisions with file:line evidence
- [x] `pytest` still exits 0 after the leg (xfail tests count as "expected failure" and don't fail the suite) — 10 passed, 0 failed, 0 xfailed
- [x] If fix happens: no regression in playlist smoke or other paths — pytest suite (10 tests including F1 takeover) clean; smoke scripts are pre-existing broken (see Anomalies)
- [x] `tests/_fakes.py` is NOT modified to import `soco` — keep the fake SoCo-free per its module docstring. If a test needs to raise `SoCoSlaveException`, import it in the test file (`from soco.exceptions import SoCoSlaveException`) and use it there
- [x] All investigation-only `print(..., file=sys.stderr)` instrumentation is removed from `controller.py` before commit

## Verification Steps
- **Bug reproduction**: `.venv/bin/pytest tests/test_say_coordinator.py -v` (or wherever the test lands) — shows the test reproducing the bug deterministically
- **If fix lands**: `.venv/bin/python smoke_test.py` succeeds with `say(Kitchen, "...")` — first clean smoke run since Flight 01 Leg 01
- **If `xfail` lands**: `.venv/bin/pytest -v` shows the test as `XFAIL` (expected failure); the suite exits 0
- Flight log Decisions section documents the fix-vs-xfail call with evidence

## Implementation Guidance

**Phase A — Reproduce the bug as a test (always required)**:

1. Read `mcp_sonos/controller.py::say()` and `_resolve_coordinator` to understand the current call shape. The bug fires at `coord.play_uri(...)` inside `say()`.

2. Look at the SoCo library briefly to understand when `play_uri` raises `SoCoSlaveException`. Per CLAUDE.md (line 108-111): "Sonos transport commands only work on the coordinator. SoCo raises `SoCoSlaveException` if you call `play_uri` on a follower."

3. Construct a `SoCoFake` configuration that triggers the same error. **Start with Path A**; fall back to Path B only if Path A can't reproduce:
   - **Path A (try first — most likely cause) — `SoCoFake.play_uri` raises when not coordinator**: extend the fake to track `is_coordinator` and raise `SoCoSlaveException` (imported from `soco.exceptions`) if `play_uri` is called when the fake is in a group but not the coordinator. Then construct a state where the controller's resolved `coord` IS a coordinator per SoCo's `group.coordinator` view but the FAKE has `is_coordinator=False` (modeling firmware-vs-SoCo divergence). Exercises hypothesis #1 (stale cached SoCo). **Flight 03's debrief evidence — `list_groups` reporting target as singleton coordinator while `say()` still fails — points squarely at this hypothesis.**
   - **Path B (fallback) — Force `_resolve_coordinator` into the lull state**: SoCo briefly returns `group.coordinator=None` after rapid topology changes. The fake can simulate this by setting `group.coordinator = None`. Then `_coordinator_of` returns the speaker itself; if the speaker is actually a follower, `play_uri` fails. Exercises hypothesis #2. Less likely given the debrief evidence; reserve for if Path A doesn't reproduce.

4. **Import `SoCoSlaveException` in the TEST file**, not in `tests/_fakes.py`. The fake module docstring explicitly says "intentionally independent of the real SoCo library" — respect that boundary. The test imports `from soco.exceptions import SoCoSlaveException` and monkey-patches `SoCoFake.play_uri` (or subclasses `SoCoFake`) to raise it in the bug-triggering configuration.

5. Write the test such that it WOULD fail today against the current `controller.py`. Run pytest — confirm it fails (or `xfail`s, depending on how you structure it).

**Phase B — Investigate root cause**:

1. With the failing test in hand, add investigation-only instrumentation to `controller.py:say()`. `controller.py` has no module logger configured — use `print(..., file=sys.stderr)` for the spike (and **remove before commit**):
   ```python
   import sys
   def say(self, target, text, ...):
       s, coord = self._resolve_coordinator(target)
       print(f"say: target={target!r} resolved s={s.player_name} coord={coord.player_name} "
             f"coord.group.coordinator={getattr(coord.group, 'coordinator', None) and coord.group.coordinator.player_name}",
             file=sys.stderr)
       ...
   ```
   Run smoke against live hardware (or the failing test) to see what divergence occurs at the call site. Remove all `print(..., file=sys.stderr)` lines before committing.

2. Compare what `coord.uid` is vs what `coord.group.coordinator.uid` is. If they differ, the speaker SoCo claims to be a coordinator while its own group view says otherwise — that's the bug.

3. The fix likely lies in `_coordinator_of` or `_resolve_coordinator` — possibly a freshness issue with the SoCo cache or a transient None lull.

**Phase C — Fix-or-xfail decision**:

Apply the surface-area scope guard from Context. Judge by what files/symbols the diff touches:

1. **In-scope fix paths** (proceed with fix):
   - `controller.py::_coordinator_of` — e.g. prefer `coord.group.coordinator` over `coord` when they differ
   - `controller.py::_resolve_coordinator` — e.g. retry once on `SoCoSlaveException`, refresh SoCo state before resolving
   - `controller.py::say()` — e.g. wrap `play_uri` with a retry-then-rediscover guard
   - `controller.py::_speakers_fresh` — e.g. force re-discovery when a stale-coordinator condition is detected

   Implement, re-run the test, re-run `smoke_test.py` (only verifiable on a machine with reachable Sonos hardware — flag in flight log if hardware unavailable), update mission Known Issues to mark resolved.

2. **Out-of-scope (switch to xfail)**:
   - Fix requires changes to `playlists.py` worker
   - Fix requires modifications to SoCo library internals
   - Fix requires adding a NEW cache layer beyond `_speakers_fresh`
   - Fix requires cross-module reconciliation

   Mark the test `@pytest.mark.xfail(reason="say() coordinator bug — see mission Known Issues")`.
   Update mission Known Issues with the investigation findings, structured as:
   - (a) which hypothesis the reproduction confirmed (#1 stale-cached-SoCo, #2 lull-state, or other)
   - (b) the divergence observed (`coord.uid` vs `coord.group.coordinator.uid`, or whatever the spike found)
   - (c) the fix shape that would resolve it (concrete diff sketch, not vague intent)
   - (d) why it's out of scope for this flight (cite the surface guard — which file/symbol the fix would touch)

3. **Either way**: capture the decision in flight log Decisions with file:line evidence.

## Files Affected
- `tests/test_say_coordinator.py` — new (or extension of an existing test file in Leg 03's set)
- `tests/_fakes.py` — possibly extended (e.g. add `SoCoSlaveException`-equivalent + `is_coordinator` state)
- `mcp_sonos/controller.py` — IFF the fix lands; otherwise untouched
- `missions/01-baseline-maintenance/mission.md` — Known Issues entry updated (either resolved or expanded with findings)

## Edge Cases
- **`_verified_voices` cache pollution**: not relevant for `say()` bug investigation (different code path).
- **SoCo library exceptions**: the actual SoCo class for "called on slave" is `SoCoSlaveException` (real library). Tests using `SoCoFake` should raise a similar exception class — either import the real one from `soco.exceptions` or define a fake-only class for tests. Either is fine; the real one is more honest.
- **Worker thread cleanup**: if the test exercises the playlists worker path via `say()` interrupt, ensure worker shutdown is clean (same as Leg 03's takeover test).
- **Smoke test regression risk**: if the fix lands, run BOTH smoke scripts to confirm no new failure mode. `playlist_smoke.py` exercises `say()` indirectly via takeover detection.
- **CLAUDE.md update**: if the fix lands, `CLAUDE.md` line 108-111 ("Sonos transport commands only work on the coordinator") may need a follow-up note about the fix's handling. Optional in this leg; could defer.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Test reproduces the bug deterministically (or fix makes it pass — match the chosen outcome) — fix in place; 2 tests pin both halves of the recovery path
- [x] `pytest` exits 0 (xfail counts as expected failure, not test failure) — 10 passed
- [x] If fix lands: smoke `say()` passes; mission Known Issues entry updated to resolved — Known Issue marked `[x]`; smoke verification deferred due to NEW unrelated Known Issue (smoke scripts broken by Leg 02 DI regression)
- [x] If `xfail`: mission Known Issues entry expanded with investigation findings and next steps — N/A (FIX outcome)
- [x] Flight log Decisions section documents the fix-vs-xfail call with rationale
- [x] Update `../flight-log.md` with leg progress entry
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
