# Leg: parametrize-skip-guard-tests

**Status**: ready
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Parametrize the three near-identical skip-guard tests into one parametrized test over the guard conditions (finding T-4).

## Context
- Maintenance report 2026-06-02, finding **T-4** (Advisory, Test Systems / overlapping tests).
- `tests/test_queue_resume.py:223,244,265` — `test_no_queue_skip_no_play_from_queue`, `test_not_playing_skip_no_play_from_queue`, `test_playlist_position_zero_skip_no_play_from_queue` — each hand-build a `SoCoFake` with a full inline `_track` dict differing in exactly one field (queue empty / transport STOPPED / position "0") and assert the identical `play_from_queue_last_index is None`.
- The guard is one logical OR with three terms, currently tested as three fully-duplicated setups (~25 lines of duplicated track dicts).
- Depends on leg 05 (shared builder with overrides).

## Inputs
- `tests/test_queue_resume.py` skip-guard tests
- The shared builder (with overrides) from leg 05
- Green suite

## Outputs
- One parametrized test over `(queue, transport_state, playlist_position)` asserting `play_from_queue_last_index is None` for each guard-triggering condition, using the shared builder.

## Acceptance Criteria
- [ ] The three skip-guard tests are replaced by one `@pytest.mark.parametrize` test covering the three guard conditions (empty queue / not-playing / position zero)
- [ ] Each case uses the leg-05 builder with a single-field override, not a full inline `_track` dict
- [ ] The assertion (`play_from_queue_last_index is None`) is identical to before for each case
- [ ] Full suite green; ~25 lines of duplicated track dicts removed

## Verification Steps
- `pytest tests/test_queue_resume.py -v` (venv active) → the parametrized skip-guard test shows its three variants, all green
- `grep -n "skip_no_play_from_queue" tests/test_queue_resume.py` → one parametrized test, not three
- `pytest` (full suite) → green

## Implementation Guidance

1. **Parametrize over the guard conditions** — `(queue, transport_state, playlist_position)` triples, each representing one OR-term that should suppress the resume: `(empty, PLAYING, "1")`, `(non-empty, STOPPED, "1")`, `(non-empty, PLAYING, "0")`. Build the speaker via the leg-05 builder with the single overridden field.

2. **Assert the shared expectation** — `play_from_queue_last_index is None` for every case.

## Edge Cases
- **Keep the three conditions distinct in the parametrize IDs** so a failure
  names which guard term broke (use `pytest.param(..., id="empty-queue")` etc.).
- If a fourth guard term exists in the code that wasn't tested before, this is a
  dedup leg — do not add new coverage here; note it for a future leg if spotted.

## Files Affected
- `tests/test_queue_resume.py` - parametrize the three skip-guard tests

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
