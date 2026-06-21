# Leg: extract-live-track-dict

**Status**: landed
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Extract the triplicated live-coordinator-read dict in `playlists.py` into one helper, reconciled against `controller.py` `_track_state` (finding I-5).

## Context
- Maintenance report 2026-06-02, finding **I-5** (Action Required, Code Quality / dedup).
- `playlists.py` builds the same live-track dict in three places — `next_track`, `previous_track`, and `status` (the three sites read `coord.get_current_track_info()`; they sit roughly in `playlists.py:411-506`, line numbers drift slightly between reviewer reports — locate by the `get_current_track_info()` reads).
- The dict shape is `{engine, speaker, title, artist, album, position, duration, uri, playlist_position}`. `next_track` and `previous_track` are near-identical (differ only in `coord.next()` vs `coord.previous()`).
- The shape also **diverges** from `controller.py:39` `_track_state` (different key defaults — `""` vs `None`, plus `playlist_position`), so the two live-state readers can drift apart independently.

> **Design-review note (verified against code):** the three sites are
> `next_track` (`playlists.py:413`), `previous_track` (`:442`), `status` (`:490`);
> `_track_state` is at `controller.py:39`. **The two readers are structurally
> incompatible — do NOT force a shared base.** `_track_state` uses `.get(key)`
> (→ `None`) and carries a `state` key but no `engine`/`speaker`/`playlist_position`;
> the playlists sites use `.get(key, "")` (→ `""`) and carry
> `engine`/`speaker`/`playlist_position` but no `state`. The correct outcome is
> ONE `_live_track_dict` helper for the three **playlists** sites, plus a comment
> documenting the deliberate divergence from `_track_state` (not a merged base).
> **Behavior-preservation:** `status` has an early-return guard (around `:493-494`,
> `if state in ("STOPPED", "") or not track.get("uri")` → minimal dict) — that
> guard must stay in `status` BEFORE the helper call, never inside the helper.

## Inputs
- `mcp_sonos/playlists.py` with the three live-read sites
- `mcp_sonos/controller.py` `_track_state`
- Green suite

## Outputs
- One `_live_track_dict(coord, speaker_name)` helper (name/signature at implementer's discretion) in `playlists.py`, used by all three sites.
- `next_track`/`previous_track` collapsed to call the helper with the appropriate bound method.
- A reconciliation note (comment) on how this relates to `controller.py` `_track_state` — either share a base or explicitly document why the two intentionally differ.

## Acceptance Criteria
- [ ] A single helper builds the live-track dict in `playlists.py`; the three sites call it
- [ ] `next_track` and `previous_track` no longer duplicate the dict-building block (only the `coord.next()`/`coord.previous()` call differs)
- [ ] The relationship to `controller.py` `_track_state` is reconciled: either the two share a helper, or a comment documents the deliberate key-default divergence so a future reader does not "fix" one to match the other
- [ ] Full suite green; the returned dicts are byte-for-byte the same as before (same keys, same defaults, same `playlist_position` conversion)

## Verification Steps
- `pytest` (venv active) → all green; the status/next/previous tests (in `test_queue_path.py`, `test_queue_resume.py`) assert the dict contents and are the regression net
- `grep -n "get_current_track_info" mcp_sonos/playlists.py` → reads now funnel through the one helper
- Read the helper and confirm the `playlist_position` 1-based→0-based handling is preserved exactly

## Implementation Guidance

1. **Extract the helper** — `_live_track_dict(coord, speaker_name)` returns the
   full dict from `coord.get_current_track_info()` with the existing key defaults
   and the `engine`/`playlist_position` fields. Keep the try/except posture each
   site currently has (do not change error handling).

2. **Migrate the three sites** — `status` calls it directly; `next_track`/
   `previous_track` advance first (`coord.next()`/`coord.previous()`), then call
   the helper. If the advance + read is itself a pattern, a thin
   `_advance_and_read(coord, advance_fn, speaker_name)` is acceptable but not
   required.

3. **Reconcile with `_track_state`** — inspect `controller.py:39`. If the two can
   share a base without changing either's output, do so. If their key defaults
   genuinely must differ (the controller's consumers vs the playlist consumers),
   add a one-line comment at both sites pointing at the other so the divergence
   is intentional and visible.

## Edge Cases
- **Title unreliability**: per the Mission-02 debriefs, `now_playing.title` is
  unreliable for queued items (Sonos prefers ID3 over DIDL) — the helper must
  preserve whatever the current sites do here (they read the field but callers
  know to prefer artist/album). Do not "fix" this in a dedup leg.
- **`playlist_position` conversion**: the 1-based→0-based handling is a pinned
  invariant (tested) — preserve it exactly.

## Files Affected
- `mcp_sonos/playlists.py` - extract helper; collapse the three sites
- `mcp_sonos/controller.py` - (read-only reconciliation; comment only, unless a shared base is cleanly extractable)

---

## Post-Completion Checklist

**Complete ALL steps before signaling `[COMPLETE:leg]`:**

- [ ] All acceptance criteria verified
- [ ] Tests passing
- [ ] Update flight-log.md with leg progress entry
- [ ] Set this leg's status to `completed`
- [ ] Check off this leg in flight.md
- [ ] Commit
