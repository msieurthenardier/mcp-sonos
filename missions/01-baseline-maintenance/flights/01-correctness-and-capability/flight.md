# Flight: Correctness and Capability Hardening

**Status**: in-flight
**Mission**: [Baseline Maintenance](../../mission.md)

## Contributing to Criteria
- [ ] F1 — `playlists.py:380` no longer references a nonexistent attribute
- [ ] F2 — `play_file` rejects paths outside `AUDIO_MEDIA_ROOT`; audio host directory listing disabled
- [ ] F3 — `AUDIO_PORT` outside 8000–8999 raises a clear `ValueError`
- [ ] F5 — `say()` (and any other group-access site) routes through `_group_members_of`
- [ ] F12 — `audio_host.url_for` URL-encodes filenames
- [ ] F14 — `play_url` and playlist URL inputs reject non-`http`/`https` schemes

---

## Pre-Flight

### Objective
Land the real correctness bug fix, scope `play_file` to a configured media root (closing the one finding that crosses the documented threat model), and harden the input-validation surface around the audio host and URL handling. All six legs touch `mcp_sonos/controller.py`, `mcp_sonos/audio_host.py`, `mcp_sonos/server.py`, or `mcp_sonos/playlists.py`; they're independent fixes with no design ambiguity.

### Open Questions
N/A — fixes are concrete; design decisions captured below.

### Design Decisions

**AUDIO_MEDIA_ROOT filters at controller, not at serve root**: The audio HTTP serve root (`/tmp/mcp-sonos-audio/`) is shared between TTS WAVs (written by Piper) and `play_file`-staged copies. F2's allow-list therefore filters `play_file` *inputs* in `controller.py` before `audio.stage(p)` is called. `stage()` itself is unchanged.
- Rationale: TTS must continue to land in the serve root; only `play_file` is the threat-crossing surface
- Trade-off: validation lives in `controller.play_file` rather than `AudioHost.stage` — less universal but more precise. Recon surfaced this; the original maintenance report didn't distinguish the two surfaces

**AUDIO_MEDIA_ROOT default**: If unset, `play_file` is disabled (returns a clear error pointing at the env var). Don't default to `~/Music` — too implicit.
- Rationale: explicit is safer than implicit for a capability that crosses the threat model
- Trade-off: existing scripts/agent flows that called `play_file` will get a clear error until `AUDIO_MEDIA_ROOT` is set; one-time configuration cost

**Directory-listing disabled by subclassing**: Override `list_directory` in the existing `Handler` subclass in `audio_host.py:57-62` to return 404. The serve root is a cache directory, not a browse target.
- Rationale: cleaner than dropping an `index.html`; subclass already exists for `log_message` silencing
- Trade-off: none

**Port range constant**: Validate against the existing `PORT_RANGE` constant (`audio_host.py:19`, already used by the auto-selection path); raise `ValueError` with a message naming the firewall rule.
- Rationale: reuse the constant that drives auto-pick
- Trade-off: none

**F5 helper option**: `_group_members_of` returns sorted speaker **names** (strings), not SoCo objects (verified at `controller.py:63-69`). The `say()` inline block needs SoCo objects to set per-member volume. Refactor: call `_group_members_of(coord)`, then `[self._resolve(n) for n in member_names]`. Don't extend the helper to optionally return SoCo objects — that bloats its contract for one caller.
- Rationale: preserves the helper's single-purpose API; one map call is cheap
- Trade-off: an extra resolve hop per call; acceptable

**URL scheme allow-list**: Apply at the tool surface (`server.py`) for `play_url`; also apply at `playlists.add`/`add_many` since those carry the same risk. Lowercase before compare. Reject anything not in `{http, https}` with a clear validation error.
- Rationale: enforce at the boundary, agent sees a clean MCP error
- Trade-off: tool-side validation is duplicated if controller is called from a non-MCP context — acceptable

### Prerequisites
- [ ] Pre-flight baseline: smoke tests pass against live hardware (record timestamp in flight log)

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [ ] Pre-flight baseline recorded in flight log
- [x] Validation approach defined (smoke-test coverage notes in In-Flight section)
- [x] Legs defined
- [x] Design reviewed by Architect (notes in flight log)

---

## In-Flight

### Technical Approach
Six discrete legs, each scoped to one finding. F2 is the largest (env var + path validation + extension allow-list + disable directory listing); the others are 5–15 line changes.

**Commit cadence**: one commit per leg. The legs are independent and revertable; per-leg commits keep `git bisect` and selective revert trivial if a later leg surfaces a regression in an earlier one. The flight log gets an entry per leg too — code + log entry land together.

**Smoke-test coverage during the flight is incomplete by design**:
- `smoke_test.py` exercises F5 (the `say()` paths) — the F5 leg is well-covered.
- `playlist_smoke.py` exercises the takeover branch (F1) only if a `say()` or `play_url()` interrupts the playlist mid-run, which the current script does NOT trigger. F1's takeover path is therefore exercised by manual one-shot verification.
- **F2, F3, F12, F14 are NOT covered by either smoke test.** They ride on the explicit manual verifications listed in Post-Flight Verification.
- Optional: add a one-line `say()` mid-playlist call to `playlist_smoke.py` to exercise F1's clean-warning path; defer if it expands scope.

### Checkpoints
- [ ] F1 lands and external-takeover detection logs cleanly (manual repro via `playlist_smoke.py` style takeover)
- [ ] F2 lands and `play_file` rejects out-of-root paths; `say()` still works (TTS cache is in the serve root)
- [ ] F3 lands and starting the server with `AUDIO_PORT=9999` errors out
- [ ] F5 lands and `say(target="all", ...)` still works
- [ ] F12 lands and `play_file` with a space-in-name file works
- [ ] F14 lands and `play_url("file:///etc/passwd")` is rejected at the MCP boundary

### Adaptation Criteria

**Divert if**:
- F2's `AUDIO_MEDIA_ROOT` change breaks the existing TTS-cache-in-the-serve-root assumption (the serve root holds two things: TTS WAV files written by Piper, and `play_file`-staged copies). If keeping them in the same root makes the allow-list logic awkward, split into two roots.

**Acceptable variations**:
- Adjusting the exact error message format
- Bundling F6 (dead lock + import) into this flight if it's natural while touching `controller.py`

### Legs

- [x] `01-fix-playlist-takeover-attribute` — F1: fix `playlists.py:380` AttributeError
- [x] `02-constrain-play-file-to-media-root` — F2: AUDIO_MEDIA_ROOT + extension allow-list + disable directory listing
- [ ] `03-validate-audio-port-range` — F3: enforce 8000–8999 at parse time
- [ ] `04-route-say-through-group-members-helper` — F5: `say()` uses `_group_members_of`
- [ ] `05-url-encode-audio-host-filenames` — F12: `urllib.parse.quote` in `url_for`
- [ ] `06-restrict-play-url-schemes` — F14: allow-list `http`/`https` at the tool surface

---

## Post-Flight

### Completion Checklist
- [ ] All 6 legs completed (each with its own commit)
- [ ] Smoke tests pass against live hardware (basic + playlist) at flight end
- [ ] Maintenance report findings F1, F2, F3, F5, F12, F14 ticked in `missions/01-baseline-maintenance/mission.md`
- [ ] Flight log filled in (per-leg entries + final summary)

### Verification
- `playlist_smoke.py` exercises the takeover branch — log output should include the new clean warning, not an AttributeError trace caught by the outer except.
- Manual: `mcp-sonos` with `AUDIO_PORT=9999` fails at startup with a clear error.
- Manual: `play_file("Kitchen", "/etc/passwd")` returns a validation error, not "success."
- Manual: `play_file("Kitchen", "<file under AUDIO_MEDIA_ROOT>")` works as before.
- Manual: `play_url("Kitchen", "file:///etc/passwd")` returns a validation error.
- Manual: `GET http://<HOST_IP>:<AUDIO_PORT>/` returns 404 instead of an HTML listing.
