# Leg: hardware-discovery-verification

**Status**: completed
**Flight**: [Zero-Config Discovery](../flight.md)

## Objective
Verify zero-config discovery on the operator's real household by running
behavior test `zero-config-discovery`.

## Context
- Legs 01–02 were committed as `b9dee81`, and the draft PR is #11.
- This leg adds no code. It is acceptance verification run by the Flight
  Director via `/mission-control:behavior-test zero-config-discovery`, which
  uses an Executor and a Validator in the Witnessed pattern.
- Discovery is read-only: no audio, grouping or volume changes.
- The timing expectations were revised in flight after leg 02: a cold first
  call under 5 s, and every later call under 1.5 s.

## Inputs
- `discovery_smoke.py` is at the repo root.
- The household is powered on, with speakers at `.49–.53` and the Boost at
  `.48`.

## Outputs
- A run log at `tests/behavior/zero-config-discovery/runs/{timestamp}.md`,
  committed.
- A flight-log entry referencing the run log.

## Acceptance Criteria
- [ ] `/mission-control:behavior-test zero-config-discovery` passes all 8 steps.
  - Step 7 may instead be recorded as an environment deviation if SSDP
    unexpectedly finds speakers, as the spec allows.

## Verification Steps
- The run log's verdict is PASS for every step.

## Implementation Guidance
1. **Run the behavior test.** The Flight Director runs it.
2. **On failure:** investigate, fix via a Developer in a *new* commit (no
   amend), re-review, and re-run.
3. **Do not land the leg while the test fails**, unless the operator accepts
   the failure as a known issue.

## Edge Cases
- **Transient LAN anomaly:** re-run once and record both runs. Don't mask it.

## Files Affected
- `tests/behavior/zero-config-discovery/runs/*.md` (new)
- `tests/behavior/zero-config-discovery.md` (the `Status` and `Last Run`
  fields)

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow. Not repeated here.
