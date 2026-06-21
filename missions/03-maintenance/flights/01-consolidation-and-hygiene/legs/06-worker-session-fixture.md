# Leg: worker-session-fixture

**Status**: landed
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Extract the repeated worker-session lifecycle boilerplate into a `worker_session` context-manager fixture, fixing the missing-`mgr.stop` cleanup at `test_queue_path.py:520` (finding T-6).

## Context
- Maintenance report 2026-06-02, finding **T-6** (Advisory, Test Systems / dedup).
- Four tests repeat the same 6-line worker-thread dance — save `POLL_INTERVAL`, set it to `0.01`, create an MCP-hosted playlist, play, assert the session, then `finally` restore + stop:
  - `test_queue_path.py:271` `test_queue_play_evicts_worker_before_queue_load`
  - `test_queue_path.py:460` `test_worker_session_path_unchanged_for_next`
  - `test_queue_path.py:490` `test_worker_session_path_unchanged_for_previous`
  - `test_queue_path.py:520` `test_worker_session_stop_returns_engine_worker`
- **`:520` omits the `mgr.stop` cleanup the other three have** — a real inconsistency / latent fixture leak. Extracting one fixture fixes it uniformly.

## Inputs
- `tests/test_queue_path.py` with the four worker-session tests
- Green suite

## Outputs
- A `worker_session(mgr, speaker)` context manager / fixture that patches `POLL_INTERVAL`, starts the worker, yields, and **guarantees** restore + `mgr.stop` on exit.
- The four tests use it; the `:520` cleanup gap is closed.

## Acceptance Criteria
- [ ] A single `worker_session` context manager / fixture encapsulates the patch-start-yield-restore-stop lifecycle
- [ ] All four worker-session tests use it; none hand-rolls the `POLL_INTERVAL` save/restore + `finally` dance
- [ ] The `test_queue_path.py:520` test now restores `POLL_INTERVAL` and calls `mgr.stop` (via the shared cleanup) — the inconsistency is gone
- [ ] Full suite green; no behavior change (the eviction-timing assertion in `test_queue_play_evicts_worker_before_queue_load` still holds — it patches `clear_queue` to assert the worker is dead at call time)

## Verification Steps
- `pytest` (venv active) → all green
- `grep -n "POLL_INTERVAL" tests/test_queue_path.py` → the save/restore appears only inside the fixture, not in each test
- Read the fixture and confirm the `finally`/`__exit__` always restores `POLL_INTERVAL` and stops the manager

## Implementation Guidance

1. **Write the context manager** — `@contextmanager def worker_session(mgr, speaker): save = mgr.POLL_INTERVAL (or module const); set 0.01; create+play MCP-hosted playlist; try: yield session; finally: restore; mgr.stop()`. Exact shape depends on how `POLL_INTERVAL` is referenced today (module constant vs attribute) — match it.
   - If a pytest fixture fits better than a context manager (e.g. the tests want
     it as a parameter), that is equally acceptable; the requirement is one
     shared lifecycle with guaranteed cleanup.

2. **Migrate the four tests** — replace each hand-rolled block with `with worker_session(mgr, speaker) as session:` (or the fixture parameter). Preserve each test's distinct assertions (eviction timing, next/previous unchanged, stop returns `engine: worker`).

## Edge Cases
- **The eviction-timing test** patches `clear_queue` to assert the worker thread
  is dead at call time — the fixture must not interfere with that patch or the
  ordering. Keep the play/assert inside the `with` body.
- **`POLL_INTERVAL` reference style** — confirm whether it's a module-level
  constant or a manager attribute before writing the save/restore.

## Files Affected
- `tests/test_queue_path.py` - add the fixture/context manager; migrate four tests
- (or `tests/conftest.py` / `tests/_builders.py` if co-located with leg 05's helpers)

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
