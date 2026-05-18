# Leg: 01-fix-playlist-takeover-attribute

**Status**: ready
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
Fix the AttributeError at `mcp_sonos/playlists.py:380` by replacing the nonexistent `session.coordinator_name` reference with the correct field on `PlaybackSession` (Finding F1 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `PlaybackSession` (dataclass at `playlists.py:60-83`) defines only `speaker_uid` and `speaker_name`. There is no `coordinator_name` field.
- The reference is inside the external-takeover detection branch (`if state == "PLAYING" and current_uri and current_uri != item.url:`), which the codebase explicitly relies on as the normal path for `say`/`play_url`/manual-app-takeover to terminate playlists cleanly (CLAUDE.md:82-85).
- The outer `except Exception:` at `playlists.py:398` catches the AttributeError, so playback still ends — but the warning log is lost and the worker exits via the crash path rather than the clean break.
- Architect's recommendation: use `session.speaker_name`. Either is semantically right at this log site (the keying is per-speaker, so logging the speaker name is honest).

## Inputs
- `mcp_sonos/playlists.py` with the broken reference at line 380

## Outputs
- `mcp_sonos/playlists.py` with the reference fixed
- No other behavior changes

## Acceptance Criteria
- [ ] `mcp_sonos/playlists.py:380` no longer references a nonexistent attribute
- [ ] External-takeover detection emits a `warning`-level log naming the speaker (verified by inducing a takeover during testing)
- [ ] Worker exits via the clean `advance=False; stop_event.set(); break` path, not via the outer `except Exception:`
- [ ] No other call sites in `playlists.py` reference `coordinator_name` (grep to verify)

## Verification Steps
- `grep -n "coordinator_name" mcp_sonos/playlists.py` returns no hits after the fix.
- Manually exercise: with live Sonos hardware, start a playlist via `playlist_smoke.py` or equivalent, then call `say("<speaker>", "test")` to trigger the takeover branch. Check process logs for the new clean warning rather than an `AttributeError` traceback.

## Implementation Guidance

1. **Open `mcp_sonos/playlists.py`** and locate the block around line 376-385:
   ```python
   if state == "PLAYING" and current_uri and current_uri != item.url:
       log.info(
           "playlist %r preempted on %s by %s — stopping",
           session.playlist_name,
           session.coordinator_name,   # ← undefined attribute
           current_uri,
       )
       advance = False
       session.stop_event.set()
       break
   ```

2. **Replace** `session.coordinator_name` with `session.speaker_name`.

3. **Confirm `log.info` is the right level.** Architect framed this as a `warning` in the finding, but the codebase has been logging it at `info`. Match the surrounding style — keep `log.info` unless a strong reason emerges to lift it.

4. **Grep** the rest of `playlists.py` for any other `coordinator_name` references — should be none, but verify.

## Files Affected
- `mcp_sonos/playlists.py` — single one-word change on line 380 (and possibly an additional grep-cleanup elsewhere)

## Edge Cases
- None — the field exists; this is a straight rename.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes (or live takeover manually reproduced cleanly)
- [ ] Update `../flight-log.md` with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in `../flight.md`
