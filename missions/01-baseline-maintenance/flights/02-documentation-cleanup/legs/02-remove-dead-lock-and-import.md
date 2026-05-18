# Leg: 02-remove-dead-lock-and-import

**Status**: ready
**Flight**: [Documentation Cleanup](../flight.md)

## Objective
Remove the unused `from typing import Iterable` and the abandoned `self._lock = threading.Lock()` from `mcp_sonos/controller.py` (Finding F6 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `controller.py:14` imports `Iterable` from `typing`; the symbol is never referenced.
- `controller.py:94` creates `self._lock = threading.Lock()`. The grep audit found one occurrence — only the assignment. The actual playlist locking lives in `PlaylistManager._lock`.
- This is misleading: a reader sees a `threading.Lock` in the controller and assumes thread-safety. The controller has no actual synchronization on `_speakers` / `_speakers_ts` between concurrent FastMCP tool calls.
- The FastMCP event loop is currently single-threaded, so no realized race exists today — but the abandoned lock is a code smell that will mislead a future contributor into thinking they don't need to add synchronization when they later parallelize.

## Inputs
- `mcp_sonos/controller.py:14, 94`

## Outputs
- Lines 14 and 94 cleaned up
- No functional behavior change

## Acceptance Criteria
- [ ] `from typing import Iterable` removed (if no other typing imports are present, drop the `from typing` line entirely; if other symbols are used, leave those)
- [ ] `self._lock = threading.Lock()` removed
- [ ] `grep -n "_lock\|Iterable" mcp_sonos/controller.py` returns no hits (other than legitimate uses elsewhere in `PlaylistManager` if relevant)
- [ ] Smoke tests still pass

## Verification Steps
- `grep -n "_lock" mcp_sonos/controller.py` returns no hits.
- `grep -n "Iterable" mcp_sonos/controller.py` returns no hits.
- `smoke_test.py` passes.

## Implementation Guidance

1. **Read** `controller.py:14` to see if `Iterable` is the only `typing` import on that line. If yes, drop the whole `from typing import Iterable` line. If others (`Optional`, `List`, etc.) are on the same line, remove only `Iterable`.

2. **Read** `controller.py:94` and delete the `self._lock = threading.Lock()` line. Check the surrounding `__init__` for any other dead state while you're there.

3. **Optionally**: if the `threading` import is no longer used in `controller.py` after removing the lock, drop the `import threading` line too.

4. **Future hardening (out of scope but worth noting in the flight log)**: if concurrent tool calls become a real concern, replace with a proper lock around `_speakers`/`_speakers_ts` reads and writes, not a single class-level lock. This is what F7 (test scaffolding) will eventually need to model.

## Files Affected
- `mcp_sonos/controller.py` — two lines deleted, possibly a third (the `import threading` line if now unused)

## Edge Cases
- None — straight deletion.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
