# Leg: hardware-targeting-verification

**Status**: completed
**Flight**: [Deterministic Target-Set Playback](../flight.md)

## Objective
Verify target-set playback on the operator's real household by running
behavior test `target-set-playback`, with every speaker muted.

## Context
- Legs 01–02 were committed as `c34d716`, and draft PR #12 is open, stacked
  on #11.
- This leg adds no code. It is acceptance verification run by the Flight
  Director via `/mission-control:behavior-test target-set-playback`, which
  uses an Executor and a Validator in the Witnessed pattern.
- Speakers are muted for the whole run and restored afterwards; see steps 1
  and 12.
- **Safety gate.** The Executor must confirm, with a live read, that all
  five speakers are muted after `mute-all`, before any `stream` or `say`
  step. If any speaker is not muted, it halts the run.
- The run also validates the followers-first merge mechanism on hardware
  (step 8), which was also probed during leg 01's review.

## Inputs
- `targeting_smoke.py` is at the repo root.
- The household is powered on.

## Outputs
- A run log at `tests/behavior/target-set-playback/runs/{timestamp}.md`,
  committed.
- A flight-log entry.

## Acceptance Criteria
- [ ] `/mission-control:behavior-test target-set-playback` passes all 12
  steps.
- [ ] Step 12 restores the saved groups, volumes and mutes, confirmed by a
  live re-read.

## Verification Steps
- The run log's verdicts are PASS for every step.

## Implementation Guidance
1. **Run the behavior test.** The Flight Director runs it.
2. **On failure:**
   - Always run `stop-all`, then `restore-state`, before investigating.
   - Fix via a Developer in a new commit.
   - Review, then re-run.

## Edge Cases
- **The stream host is unreachable.** Record it and retry once. The spec's
  preconditions note the dependency.
- **A mid-run failure** leaves the topology altered. Restore before
  anything else.

## Files Affected
- `tests/behavior/target-set-playback/runs/*.md` (new)
- `tests/behavior/target-set-playback.md` (the `Status` and `Last Run`
  fields)

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
