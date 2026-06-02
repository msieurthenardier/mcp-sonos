# Leg: verify-integration

**Status**: completed
**Flight**: [Native Queue Playback Path](../flight.md)

## Objective
Confirm the queue path is correct end-to-end: full hardware-free suite green, plus
a runnable hardware smoke script that exercises the queue path and sets up the
manual reap test (Q1) the operator performs.

## Context
- Legs 2–3 implemented the classifier, queue path, eviction, and 36 tests.
- This leg's automated half is verification + a smoke script (matching the
  existing `smoke_test.py` / `playlist_smoke.py` `SONOS_IPS` convention).
- The reap test (Q1: kill MCP, watch advance) and title-stickiness confirmation
  are **manual HAT**, performed by the operator with Flight Director guidance —
  not scripted here.
- **Docs (README/CLAUDE.md/system prompt) are mission Q7 → Flight 3**, intentionally
  out of scope for this flight. Do not edit docs here.

## Inputs
- The uncommitted Leg 2–3 changes on `flight/01-native-queue-playback`.
- Existing smoke scripts for convention (`smoke_test.py`, `playlist_smoke.py`).

## Outputs
- A queue-path smoke script (new, e.g. `queue_smoke.py`, or a clearly-separated
  addition to `playlist_smoke.py`) that, against real hardware, creates an
  all-external playlist, calls `playlist_play`, and prints the resulting engine +
  `queue_size` + now-playing so the operator can confirm the queue engaged.
- Confirmation that `pytest` is fully green.

## Acceptance Criteria
- [x] Full hardware-free suite passes (`pytest -x -q` with a timeout), no regressions
      — 36 passed in 0.25 s (2026-06-01)
- [x] A queue-path smoke script exists (`queue_smoke.py`), follows the `SONOS_IPS`
      convention, and against hardware: builds an all-external playlist, runs
      `playlist_play`, asserts/prints `engine == "native_queue"` and
      `queue_size == len(tracks)`, and prints now-playing for operator confirmation
- [x] The smoke script does NOT require the Sonos app and cleans up (stop + delete
      playlist) after itself; fails fast with a clear message if no hardware is reachable
- [x] Flight log records the automated result; the manual reap test (Q1) and
      title-stickiness check are left as operator HAT steps (Leg 5 / FD-guided)

## Verification Steps
- `pytest -x -q` green.
- Smoke script runs (operator-run against hardware) and prints the expected engine
  + queue size.

## Implementation Guidance
1. Run the full suite; fix any regression surfaced (should be none).
2. Add the queue-path smoke script mirroring the existing smoke conventions
   (`os.environ.setdefault("SONOS_IPS", ...)`, `FastMCP.Client` in-process if the
   existing smokes use it, else direct controller calls). Use external test MP3
   URLs (e.g. SoundHelix) — NOT MCP-hosted ones (those would route to the worker).
3. Print engine + queue_size + now-playing; stop + clear at the end.

## Edge Cases
- **No hardware reachable**: the smoke script should fail fast with a clear message
  (the unit suite remains the hardware-free gate).

## Files Affected
- `queue_smoke.py` (new) or `playlist_smoke.py` (extended)
- No source changes expected (verification leg); fix-only if a regression appears.
