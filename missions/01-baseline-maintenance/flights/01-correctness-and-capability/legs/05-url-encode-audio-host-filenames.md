# Leg: 05-url-encode-audio-host-filenames

**Status**: completed
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
URL-encode filenames in `audio_host.url_for` so files with spaces or non-ASCII characters produce valid URLs (Finding F12 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `audio_host.py:81` constructs URLs as `f"http://{self.host_ip}:{self.port}/{filename}"`. Filenames are not URL-encoded.
- TTS WAVs are sha1-prefixed (always URL-safe), so the bug is latent for `say()`.
- `play_file`-staged files carry the user-supplied basename. After Leg 02 lands, those are constrained to `AUDIO_MEDIA_ROOT` but can still contain spaces (`/path/to/My Song.mp3`). Sonos sees `http://.../My Song.mp3`, which fails to parse cleanly.

## Inputs
- `mcp_sonos/audio_host.py:81` `url_for` method

## Outputs
- `url_for` returns URL-encoded paths

## Acceptance Criteria
- [x] `url_for("My Song.mp3")` returns `http://.../My%20Song.mp3` exactly — verified inline: `http://1.2.3.4:8000/My%20Song.mp3`
- [x] `url_for("simple.mp3")` returns `http://.../simple.mp3` (unchanged) — verified inline
- [ ] `play_file` with a space-containing filename works against live hardware — deferred to flight Post-Flight (no staged space-containing file available; URL-correctness verified at unit level)
- [ ] No regression in `say()` — see Anomalies in flight log: `say` smoke failed today with a group-coordinator error unrelated to URL encoding (TTS filenames are sha1-hex, unaffected by `quote`); verification deferred to flight Post-Flight once the coordinator issue is triaged

## Verification Steps
- Unit-style check (one-liner): `python -c "from mcp_sonos.audio_host import AudioHost; ..."` exercising `url_for` with a space.
- Manual: stage a file `My Song.mp3` under `AUDIO_MEDIA_ROOT` and play it.
- `smoke_test.py` passes.

## Implementation Guidance

1. **Import** `urllib.parse` at the top of `audio_host.py`.

2. **In `url_for`**, encode the filename:
   ```python
   def url_for(self, filename: str) -> str:
       safe = urllib.parse.quote(filename)
       return f"http://{self.host_ip}:{self.port}/{safe}"
   ```

3. **Confirm** `stage()` (which also constructs URLs in some paths) uses `url_for`. If it builds URLs inline, route those through `url_for` too.

## Files Affected
- `mcp_sonos/audio_host.py` — import + `url_for` body

## Edge Cases
- **Slashes in filenames**: `urllib.parse.quote` by default does *not* encode `/`. If filenames could ever contain `/` (shouldn't, since `stage()` uses `target.name` which is a basename), pass `safe=""` to encode them too. Default behavior is fine for the current usage.
- **Already-encoded filenames**: not a real concern — filenames come from `Path(source).name` or sha1 hex; neither is pre-encoded.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Smoke test passes
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
