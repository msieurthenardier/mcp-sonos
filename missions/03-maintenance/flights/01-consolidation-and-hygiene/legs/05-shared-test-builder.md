# Leg: shared-test-builder

**Status**: landed
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Hoist the "playing-speaker" track/transport builder and shared constants into the (currently empty) `conftest.py` so the parametrization legs can consume them (finding T-5).

## Context
- Maintenance report 2026-06-02, finding **T-5** (Advisory, Test Systems / dedup).
- `tests/conftest.py` is empty (0 fixtures); every fixture is file-local.
- `_make_speaker_playing_queue` exists as a builder in `tests/test_queue_resume.py:59`, but `tests/test_queue_path.py:337,362,405` re-inline the same 7-field `_track` dict + `_transport = {"current_transport_state": "PLAYING"}` instead of sharing it. Field-name drift between the two copies could silently diverge.
- The constants `_HOST_IP`/`_AUDIO_PORT`/`_MCP_URL` are duplicated (`test_queue_path.py:27` and inlined elsewhere).
- **This leg is a prerequisite for legs 07 (T-3) and 08 (T-4)** — the shared builder is what makes their parametrization clean. Land this first.

> **Design-review note (verified against code):** `tests/conftest.py` is empty
> (0 bytes). `_make_speaker_playing_queue` is at `test_queue_resume.py:59`; the
> inlined dicts are at `test_queue_path.py:337,362,405`. **Correction:** the
> `_HOST_IP`/`_AUDIO_PORT`/`_MCP_URL` constants (`test_queue_path.py:27-29`) exist
> ONLY in `test_queue_path.py` — they are NOT in `test_queue_resume.py` (which
> uses a monkeypatched-controller setup, not direct `PlaylistManager`
> construction). So the constants migration is one-directional (within/ from
> `test_queue_path.py`); there is nothing to de-dup on that point in
> `test_queue_resume.py`. `POLL_INTERVAL` is a module-level constant at
> `playlists.py:48`, patched via `playlists_mod.POLL_INTERVAL` — save/restore the
> module attribute, not a manager attribute.

## Inputs
- `tests/conftest.py` (empty)
- `tests/test_queue_resume.py` with `_make_speaker_playing_queue`
- `tests/test_queue_path.py` with the inlined dicts + constants
- Green suite

## Outputs
- A shared playing-speaker builder (and the `_HOST_IP`/`_AUDIO_PORT`/`_MCP_URL` constants) in `conftest.py` (or a `tests/_builders.py` imported by both files — implementer's choice; `conftest.py` is the idiomatic spot for fixtures, a `_builders.py` module for plain helper functions).
- `test_queue_path.py` and `test_queue_resume.py` import the shared builder instead of re-defining/inlining it.

## Acceptance Criteria
- [ ] One canonical playing-speaker builder is shared by both test files
- [ ] The inlined `_track`/`_transport` dicts in `test_queue_path.py:337,362,405` are replaced by calls to the shared builder
- [ ] `_HOST_IP`/`_AUDIO_PORT`/`_MCP_URL` are defined once and imported, not duplicated
- [ ] Full suite green with identical behavior (no assertion changed — this is pure setup consolidation)

## Verification Steps
- `pytest` (venv active) → all green
- `grep -rn "_make_speaker_playing_queue\|current_transport_state" tests/` → the builder is defined once; the inlined transport dicts are gone from `test_queue_path.py`
- `grep -rn "_HOST_IP\|_AUDIO_PORT\|_MCP_URL" tests/` → defined once

## Implementation Guidance

1. **Choose the home** — if the builder should accept overrides (it should, for
   legs 07/08), a plain function in `tests/_builders.py` imported by both files
   is clean; or a `conftest.py` fixture factory. Either is fine. Put the shared
   constants alongside it.

2. **Generalize the builder** — accept overrides for the fields that the
   skip-guard tests vary (`queue`, `transport_state`, `playlist_position`) so leg
   08 can parametrize against it. Default to the canonical "playing a queued
   track" state.

3. **Migrate both files** — replace the inlined dicts in `test_queue_path.py` and
   the local builder in `test_queue_resume.py` with imports of the shared one.

## Edge Cases
- **Do not change any assertion** — only the setup is being consolidated. If two
  call sites built subtly different dicts, preserve each site's exact state via
  overrides rather than homogenizing (which could weaken a test).

## Files Affected
- `tests/conftest.py` or `tests/_builders.py` - shared builder + constants
- `tests/test_queue_path.py` - import the builder; drop inlined dicts/constants
- `tests/test_queue_resume.py` - import the builder; drop the local copy

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
