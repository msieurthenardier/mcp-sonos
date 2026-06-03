# Leg: unify-stale-coord-retry

**Status**: ready
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Replace the two divergent stale-coordinator retry helpers with one shared helper that both call sites use (findings I-3 and I-4).

## Context
- Maintenance report 2026-06-02, finding **I-3** (Action Required, Code Quality / dedup) — the maintainer's top-priority axis.
- Two helpers are ~80% structurally identical:
  - `controller.py` `_play_uri_with_stale_coord_retry` (around line 386)
  - `playlists.py` `_play_from_queue_with_stale_coord_retry` (around line 651)
- Both implement: try the call → on `SoCoSlaveException`, invalidate the speaker cache → re-resolve the coordinator → retry once.
- **Three divergences the unified helper must preserve**:
  1. Cache invalidation: controller sets `self._speakers_ts = 0.0`; playlists calls the injected `self._invalidate_speakers_cache()` callback.
  2. Return contract: controller **returns** the fresh coordinator (its caller needs it for follow-up calls); the playlists twin returns `None`.
  3. Action: controller calls `play_uri(url, title=...)`; playlists calls `play_from_queue(index)`.
- Finding **I-4** (Advisory): the playlists twin's return value is dead (the recovered `fresh_coord` is discarded on the retry branch). This disappears automatically once both go through a helper that returns the fresh coordinator.
- Both retry paths are already test-covered (`test_say_coordinator.py` and `test_queue_path.py:623` `test_slave_exception_retry_flushes_cache_and_succeeds`) — the suite is the regression net for behavior preservation.

## Inputs
- `mcp_sonos/controller.py` with `_play_uri_with_stale_coord_retry`
- `mcp_sonos/playlists.py` with `_play_from_queue_with_stale_coord_retry` and an injected `_invalidate_speakers_cache` callback
- Green suite (63 tests)

## Outputs
- One shared helper (e.g. `_with_stale_coord_retry(coord, action, invalidate, resolve)` — exact signature at implementer's discretion) used by both call sites.
- The two old per-site helpers removed; no dead return value remains.

## Acceptance Criteria
- [ ] A single shared stale-coord retry helper exists; `grep -rn "stale_coord_retry" mcp_sonos/` shows the two old helper definitions gone (or reduced to thin call-site wrappers, if a wrapper is genuinely needed)
- [ ] The controller call site still receives the fresh coordinator and uses it for its follow-up calls
- [ ] The playlists call site still invalidates via the injected `_invalidate_speakers_cache` callback (not `self._speakers_ts`)
- [ ] No dead return value (I-4 resolved)
- [ ] Full suite green with no weakened or removed assertions

## Verification Steps
- `pytest` (venv active) → all green, same behavior
- `grep -rn "def .*stale_coord_retry" mcp_sonos/` → at most one definition (the shared helper)
- Read both call sites and confirm the cache-invalidation mechanism for each is unchanged

## Implementation Guidance

1. **Define the shared helper**
   - Parameterize what differs: the `action` to perform on the coordinator (a
     callable taking the coordinator), the `invalidate` callback, and the
     `resolve`/re-resolution mechanism. Return the (possibly fresh) coordinator
     so the controller path keeps its contract.
   - Place it where both modules can import it without a circular import. If
     `controller.py` and `playlists.py` would create a cycle, put the helper in
     a small module-level location (e.g. a private function in a shared util, or
     keep it in `controller.py` and inject it like the other DI callbacks). The
     existing DI pattern (`resolve_coordinator`, `invalidate_speakers_cache`
     injected into `PlaylistManager`) is the precedent — follow it.

2. **Migrate the controller call site**
   - Pass `lambda c: c.play_uri(url, title=...)` (or equivalent) as the action;
     invalidate via the controller's `self._speakers_ts = 0.0` mechanism wrapped
     in the `invalidate` callable; use the returned coordinator downstream.

3. **Migrate the playlists call site**
   - Pass `lambda c: c.play_from_queue(index)` as the action; pass
     `self._invalidate_speakers_cache` as the invalidate callable.

4. **Remove the dead return** — the playlists path now either returns the fresh
   coordinator or explicitly ignores it; no silently-discarded `fresh_coord`.

## Edge Cases
- **Circular import**: if extracting to a shared module risks a cycle, prefer
  injecting the helper (DI) over a cross-module import — matches the existing
  `PlaylistManager` constructor pattern.
- **The two invalidation mechanisms must stay semantically equal** — the
  controller's `_speakers_ts = 0.0` and the injected callback both flush the
  speaker cache; the helper must not collapse them into one mechanism that
  breaks one site.

## Files Affected
- `mcp_sonos/controller.py` - replace local helper with shared-helper call
- `mcp_sonos/playlists.py` - replace local helper with shared-helper call; remove dead return
- (possibly) a shared location for the helper, if DI is not used

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
