# Leg: smoke-and-hygiene

**Status**: completed
**Flight**: [Documentation + Smoke Coverage](../flight.md)

## Objective
Commit a reap-survival/control smoke script (Q7 smoke), add the Flight 2 debrief `# NOTE:`
source comments + fix the stale `play_url` docstring, and strike the residual "start-of-track"
wording in the Flight 2 leg artifacts.

## Context
- Behavior is already HAT-proven (Flights 1–2); this leg commits a runnable smoke + clears
  small hygiene items. No hardware run required to land.
- The throwaway `/tmp` reap_test.py + reap_control.py are the model for the committed script.

## Acceptance Criteria
- [x] A committed reap-survival smoke at repo root (e.g. `reap_smoke.py`) with **two phases**
      (one process can't reap itself): `--load` loads an all-external playlist via
      `playlist_play` and exits cleanly (the exit IS the reap); `--control` runs in a fresh
      process and drives `playlist_status` → `playlist_next` → `playlist_stop`, asserting
      `engine == "native_queue"` and that status reports live state. Uses
      `os.environ.setdefault("SONOS_IPS", ...)` with the SAME placeholder IPs as the existing
      smokes; fails fast with a clear message if no hardware; cleans up in `--control`.
- [x] The script lives at repo root so pytest (`testpaths=["tests"]`) does NOT collect it;
      confirm `pytest -q` is unaffected (stays 63)
- [x] `play_url` docstring in `controller.py` corrected: the stale "start of the interrupted
      track" wording → "resumes mid-track (best-effort; falls back to start-of-track if the
      host rejects the seek)"
- [x] `# NOTE:` comments added: controller.py at the `coord_holder` site (why the mutable
      single-cell box exists) and at the `play_mode`-restore (not restored if `play_from_queue`
      itself fails — intentional); playlists.py at `next_track`/`previous_track` no-session
      (swallow `SoCoSlaveException`, no stale-coord retry — best-effort); and a one-line
      audit-trail pointer comment at `QUEUE_PARENT_ID` (Flight 1 finding: `"-1"` loses titles)
- [x] Flight 2 artifacts: strike ONLY the stale unqualified "start-of-track" lines —
      `legs/04-queue-aware-takeover.md` **Objective** ("resume the queue at start-of-track")
      and `legs/05-verify-integration.md` objective/criterion — replace with mid-track framing.
      Do NOT alter lines that correctly describe start-of-track as the *seek fallback*.
- [x] `pytest -q` stays green (63)

## Verification Steps
- `pytest -q` green and unchanged count (63) — confirms the root script isn't collected.
- Eyeball the smoke script's two-phase flow; (optional) operator runs it against hardware.

## Implementation Guidance
1. Write `reap_smoke.py` modeled on `queue_smoke.py` conventions (in-process FastMCP Client,
   `SonosController()` + `register_tools`, `os.environ.setdefault("SONOS_IPS", ...)`); argparse
   `--load`/`--control`. `--control` asserts `engine == "native_queue"` from `playlist_status`,
   advances + stops, then cleans up (stop + delete playlist).
2. Make the source-comment + docstring edits (additive; no behavior change).
3. Edit the two Flight 2 leg artifacts — strike the precise stale lines only.

## Files Affected
- `reap_smoke.py` (new, repo root)
- `mcp_sonos/controller.py` (docstring + `# NOTE:`s), `mcp_sonos/playlists.py` (`# NOTE:`s)
- `missions/.../flights/02-reap-resilient-control/legs/04-queue-aware-takeover.md`, `legs/05-verify-integration.md`
