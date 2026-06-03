# Leg: say-all-sleep-seam

**Status**: ready
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Add a `sleep_fn` injection seam to `_say_all` so its 1.0s topology-settle sleep can be patched out in tests (finding T-1).

## Context
- Maintenance report 2026-06-02, finding **T-1** (Action Required, Test Systems).
- `_say_all` (in `controller.py`) has a hardcoded `time.sleep(1.0)` topology-settle. `tests/test_queue_resume.py::test_say_all_no_resume` therefore takes ~1.50s — ~60% of the entire suite's wall-clock; every other test is ≤0.02s.
- **This is a testability defect, not a stopwatch optimization.** A 3-second suite is fine; the problem is that the sleep is unpatchable, so every future `_say_all` test pays the full second and `_say_all` coverage is effectively capped. Frame and verify it as "the sleep is now injectable," not "the suite got faster."

## Inputs
- `mcp_sonos/controller.py` with `_say_all` and its hardcoded `time.sleep(1.0)`
- `tests/test_queue_resume.py::test_say_all_no_resume` (and any other say-all tests)

## Outputs
- `_say_all` (or the controller) takes an injectable sleep — either a `sleep_fn` parameter/attribute defaulting to `time.sleep`, or the sleep is called via `controller_mod.time.sleep` so tests can `monkeypatch.setattr` it.
- The say-all test(s) patch the sleep to a no-op, removing the 1.0s cost.

## Acceptance Criteria
- [ ] The 1.0s settle in `_say_all` is patchable without changing production behavior (default remains a real 1.0s sleep)
- [ ] `test_say_all_no_resume` (and any other say-all test) no longer pays the real 1.0s — it runs in the same ≤0.02s band as its peers
- [ ] Full suite green; production `_say_all` still sleeps 1.0s when not patched
- [ ] Total suite wall-clock drops to well under 1.5s (a confirmation signal, not the goal)

## Verification Steps
- `pytest --durations=5` (venv active) → `test_say_all_no_resume` no longer dominates; no test near 1.5s
- `pytest` → all green
- Read `_say_all` and confirm the default behavior is an unchanged real 1.0s sleep

## Implementation Guidance

1. **Pick the seam** — two clean options:
   - **Injection**: add a `sleep_fn: Callable[[float], None] = time.sleep`
     parameter to the controller (matching the existing DI style), or an
     attribute set in `__init__`. `_say_all` calls `self._sleep(1.0)`.
   - **Module-level patch point**: ensure `_say_all` calls `time.sleep(...)` via
     the module reference so a test can `monkeypatch.setattr(controller_mod.time, "sleep", lambda *_: None)`.
   - Prefer the injection seam if it matches the existing DI pattern; either
     satisfies the criterion.

2. **Patch in the say-all tests** — set the no-op sleep in
   `test_say_all_no_resume` (and any sibling). Assert the same behavior as before
   (the test's existing assertions stand).

## Edge Cases
- **Don't change the production settle** — the 1.0s topology-settle is real and
  needed on hardware; the default must still sleep 1.0s. Only tests patch it.

## Files Affected
- `mcp_sonos/controller.py` - injectable sleep in `_say_all`
- `tests/test_queue_resume.py` - patch the sleep in the say-all test(s)

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
