# Leg: parametrize-resume-tests

**Status**: ready
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Parametrize the shared resume observable across the overlapping resume tests, while preserving the tests that pin distinct behaviors (finding T-3).

## Context
- Maintenance report 2026-06-02, finding **T-3** (Action Required, Test Systems / overlapping tests) — the maintainer's priority axis.
- In `tests/test_queue_resume.py`, 7+ of the 14 resume tests assert the same pair — `play_from_queue_last_index == position-1` and `seek_last == "0:01:30"` — over near-identical setups (lines ~109, 134, 166, 185, 213, 419). The 1-based→0-based conversion is independently re-asserted 5+ times.
- **Hard constraint: do NOT collapse coverage.** Parametrize only the *shared observable*. The following pin genuinely distinct behaviors and must stay standalone:
  - `play_url` blocking + the `PLAY_URL_RESUME_TIMEOUT_SECONDS` cap (the only test pinning the timeout)
  - `play_file` delegation (inherits resume)
  - non-default `play_mode` resume
  - seek-failure (`try: seek() except: pass`) and seek-at-zero skip guards
- Depends on leg 05 (shared builder).

## Inputs
- `tests/test_queue_resume.py` with the 14 resume tests
- The shared builder from leg 05
- Green suite

## Outputs
- One parametrized test covering the shared "resumes at position-1 and seeks to snapshot" observable across `(playlist_position, expected_index)` cases.
- The behavior-specific tests retained as standalone tests.
- Net: ~4 redundant tests collapse into one parametrized case; no invariant lost.

## Acceptance Criteria
- [ ] The shared index+seek observable is asserted by one parametrized test (multiple `(playlist_position, expected_index)` cases), not re-asserted across 5+ near-identical tests
- [ ] Every distinct behavior still has a dedicated test: `play_url` blocking + `PLAY_URL_RESUME_TIMEOUT_SECONDS` cap; `play_file` delegation; non-default `play_mode`; seek-failure guard; seek-at-zero skip
- [ ] No assertion is weakened or dropped — every observable asserted before is still asserted (just consolidated where it was redundant)
- [ ] Full suite green; test count drops by ~4 with no coverage loss

## Verification Steps
- `pytest tests/test_queue_resume.py -v` (venv active) → green; the parametrized case shows its `(position, index)` variants
- Diff review: confirm each previously-asserted behavior maps to either the parametrized case (shared observable) or a retained standalone test (distinct behavior)
- `pytest` (full suite) → green

## Implementation Guidance

1. **Identify the shared core** — the tests that ONLY assert
   `play_from_queue_last_index == position-1` + `seek_last == snapshot` (and
   nothing behavior-specific) are the merge candidates. List them explicitly
   before editing.

2. **Write one `@pytest.mark.parametrize` test** over
   `(playlist_position, expected_index)` (e.g. "1"→0, "2"→1, "3"→2) using the
   leg-05 builder for setup. Assert the index conversion and the seek-to-snapshot.

3. **Preserve the behavior-specific tests** — leave the `play_url`-blocking/
   timeout test, the `play_file`-delegation test, the non-default-`play_mode`
   test, and the seek guards as their own tests. If they incidentally also assert
   the shared observable, that's fine — the point is to remove the *redundant
   standalone* copies, not to strip assertions from behavior tests.

## Edge Cases
- **The timeout test is load-bearing** — `test_play_url_resumes_queue_and_blocks`
  is the only test pinning `PLAY_URL_RESUME_TIMEOUT_SECONDS`. Never fold it away.
- **If unsure whether a test is "redundant" or "distinct"**, keep it. The
  constraint is asymmetric: over-keeping costs a few lines; over-collapsing loses
  a regression guard.

## Files Affected
- `tests/test_queue_resume.py` - parametrize the shared observable; retain behavior-specific tests

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
