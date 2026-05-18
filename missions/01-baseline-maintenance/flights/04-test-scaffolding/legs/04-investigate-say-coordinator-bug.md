# Leg: 04-investigate-say-coordinator-bug

**Status**: ready
**Flight**: [Test Scaffolding](../flight.md)

## Objective
Investigate and ideally fix the mission's only remaining real bug: `smoke_test.py` `say()` fails with `play_uri can only be called/used on the coordinator in a group` even when `list_groups` reports the target speaker (e.g. Kitchen) as its own singleton coordinator. The bug has been observed in 2 of 3 prior debrief smoke runs (Flight 01 and 03 debriefs) and is captured in mission Known Issues. Write a failing SoCoFake-driven pytest test that reproduces the bug; fix the root cause if it's small and obvious; otherwise mark `xfail` with a clear follow-up note.

## Context
- **Bug location**: `mcp_sonos/controller.py:328` (approximate; may have drifted) — `coord.play_uri(url, title=f"Say: {text[:40]}")` raises `play_uri can only be called/used on the coordinator in a group` (SoCo's `SoCoSlaveException` family).
- **Pre-debrief hypothesis** (Flight 02 debrief): Sonos household topology — coordinator changed between flight execution and debrief. **REFUTED** in Flight 03 debrief: smoke confirmed via `list_groups` that the target speaker IS its own singleton coordinator at call time. The bug is reproducible against a "should-be-coordinator" target.
- **Architect's candidate root causes** (Flight 01 debrief Anomaly Investigation):
  1. Cached SoCo for "Kitchen" has stale `is_coordinator` after a recent topology change; SoCo's `group.coordinator` view diverged from firmware reality.
  2. `_resolve_coordinator` returns the speaker itself in the `coordinator=None` lull (per `_coordinator_of` design), but Sonos rejects `play_uri` on a non-coordinator even when SoCo's view says otherwise.
- **Scope guard** (flight design decision, refined at design review): the real signal is **surface area**, not line count. **Proceed with fix** if the change is contained to `controller.py` (specifically `_coordinator_of`, `_resolve_coordinator`, or `say()` only). **Switch to xfail** if the fix requires changes to `playlists.py` worker, SoCo caching layer (e.g. `_VoiceCache`), or cross-module reconciliation. The ~30-line fallback threshold remains as a sanity check: even within `controller.py`, a fix touching 50+ lines suggests the bug's surface is bigger than this flight should absorb. The leg's success criterion is "regression test scaffolding exists for this bug," NOT "the bug is fixed."

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
- [ ] A pytest test reproduces the `play_uri can only be called/used on the coordinator in a group` error (or equivalent) against `SoCoFake` deterministically — runs in CI/local without needing live hardware to fail
- [ ] If the root cause is fixable in <30 lines: fix is implemented; test passes; smoke `smoke_test.py` `say()` path works against live hardware; mission Known Issues entry updated to "resolved by Flight 04 Leg 04 commit `<hash>`"
- [ ] If the root cause requires bigger work: test is `pytest.mark.xfail(reason="...")` with a clear pointer to the mission Known Issue; mission Known Issue entry updated with the investigation findings + concrete next steps + cited file:line evidence
- [ ] The "fix or xfail" decision is documented in the flight log under Decisions with the rationale
- [ ] `pytest` still exits 0 after the leg (xfail tests count as "expected failure" and don't fail the suite)
- [ ] If fix happens: no regression in playlist smoke or other paths

## Verification Steps
- **Bug reproduction**: `.venv/bin/pytest tests/test_say_coordinator.py -v` (or wherever the test lands) — shows the test reproducing the bug deterministically
- **If fix lands**: `.venv/bin/python smoke_test.py` succeeds with `say(Kitchen, "...")` — first clean smoke run since Flight 01 Leg 01
- **If `xfail` lands**: `.venv/bin/pytest -v` shows the test as `XFAIL` (expected failure); the suite exits 0
- Flight log Decisions section documents the fix-vs-xfail call with evidence

## Implementation Guidance

**Phase A — Reproduce the bug as a test (always required)**:

1. Read `mcp_sonos/controller.py::say()` and `_resolve_coordinator` to understand the current call shape. The bug fires at `coord.play_uri(...)` inside `say()`.

2. Look at the SoCo library briefly to understand when `play_uri` raises `SoCoSlaveException`. Per CLAUDE.md (line 108-111): "Sonos transport commands only work on the coordinator. SoCo raises `SoCoSlaveException` if you call `play_uri` on a follower."

3. Construct a `SoCoFake` configuration that triggers the same error. Two paths to try:
   - **Path A — `SoCoFake.play_uri` raises when not coordinator**: extend the fake to track `is_coordinator` and raise a `SoCoSlaveException`-equivalent if `play_uri` is called when the fake is in a group but not the coordinator. Then construct a state where the controller picks the wrong SoCo (this exercises root cause hypothesis #1).
   - **Path B — Force `_resolve_coordinator` into the lull state**: SoCo briefly returns `group.coordinator=None` after rapid topology changes. The fake can simulate this by setting `group.coordinator = None`. Then `_coordinator_of` returns the speaker itself; if the speaker is actually a follower, `play_uri` fails. (This exercises root cause hypothesis #2.)

4. Write the test such that it WOULD fail today against the current `controller.py`. Run pytest — confirm it fails (or `xfail`s, depending on how you structure it).

**Phase B — Investigate root cause**:

1. With the failing test in hand, add print/log instrumentation to `controller.py:say()`:
   ```python
   def say(self, target, text, ...):
       s, coord = self._resolve_coordinator(target)
       log.debug("say: target=%r resolved s=%s coord=%s coord.group.coordinator=%s",
                 target, s.player_name, coord.player_name,
                 getattr(coord.group, 'coordinator', None) and coord.group.coordinator.player_name)
       ...
   ```
   Run smoke against live hardware (or the failing test) to see what divergence occurs at the call site.

2. Compare what `coord.uid` is vs what `coord.group.coordinator.uid` is. If they differ, the speaker SoCo claims to be a coordinator while its own group view says otherwise — that's the bug.

3. The fix likely lies in `_coordinator_of` or `_resolve_coordinator` — possibly a freshness issue with the SoCo cache or a transient None lull.

**Phase C — Fix-or-xfail decision**:

1. **If the fix is surface-contained to `controller.py`** (`_coordinator_of`, `_resolve_coordinator`, or `say()` only — line count typically ≤30 as a sanity ceiling):
   - Implement the fix. Examples: refresh the SoCo state before `play_uri`, retry once on `SoCoSlaveException`, prefer `coord.group.coordinator` over `coord` when they differ.
   - Re-run the test — should pass.
   - Re-run `smoke_test.py` — should pass `say()` for the first time in this mission.
   - Update mission Known Issues to mark resolved.

2. **If the fix requires cross-module changes** (`playlists.py` worker, SoCo caching, etc.) OR controller.py changes >50 lines:
   - Mark the test `@pytest.mark.xfail(reason="say() coordinator bug — see mission Known Issues")`.
   - Document the investigation findings in flight log Decisions: what divergence was observed, what fix shape would address it, why it's deferred.
   - Update mission Known Issues with the investigation findings and concrete next steps. Don't close the issue.

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

- [ ] All acceptance criteria verified
- [ ] Test reproduces the bug deterministically (or fix makes it pass — match the chosen outcome)
- [ ] `pytest` exits 0 (xfail counts as expected failure, not test failure)
- [ ] If fix lands: smoke `say()` passes; mission Known Issues entry updated to resolved
- [ ] If `xfail`: mission Known Issues entry expanded with investigation findings and next steps
- [ ] Flight log Decisions section documents the fix-vs-xfail call with rationale
- [ ] Update `../flight-log.md` with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in `../flight.md`
