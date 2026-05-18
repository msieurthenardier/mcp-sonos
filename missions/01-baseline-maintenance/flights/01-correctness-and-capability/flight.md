# Flight: Correctness and Capability Hardening

**Status**: ready
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

**AUDIO_MEDIA_ROOT default**: If unset, `play_file` is disabled (returns a clear error pointing at the env var). Don't default to `~/Music` — too implicit, and an empty default forces the maintainer to make a conscious choice.
- Rationale: explicit is safer than implicit for a capability that crosses the threat model
- Trade-off: existing scripts/agent flows that called `play_file` will get a clear error until `AUDIO_MEDIA_ROOT` is set; one-time configuration cost

**Directory-listing disabled by subclassing**: Override `list_directory` to return 404 rather than dropping an `index.html` into the serve root.
- Rationale: cleaner separation; the serve root is a cache directory and shouldn't contain "real" files
- Trade-off: one extra class

**Port range constant**: Validate against the existing `PORT_RANGE` constant in `audio_host.py` (already defined for the auto-selection path); raise `ValueError` with a message naming the firewall rule.
- Rationale: reuse the same constant that drives the auto-pick logic
- Trade-off: none

**URL scheme allow-list**: Apply Pydantic validator at the tool surface (`server.py`) so the agent sees a clean validation error in the MCP response, not a SoCo exception.
- Rationale: enforce at the boundary
- Trade-off: validation duplicated if controller is called from a non-MCP context — acceptable

### Prerequisites
- [ ] Smoke tests work on user's hardware (`smoke_test.py` + `playlist_smoke.py`)

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [ ] Prerequisites verified (run smoke tests before starting)
- [x] Validation approach defined (smoke tests after each leg)
- [x] Legs defined

---

## In-Flight

### Technical Approach
Six discrete legs, each scoped to one finding. F2 is the largest (env var + path validation + extension allow-list + disable directory listing); the others are 5–15 line changes. After each leg, run the relevant smoke test against live hardware to confirm no regression. Final commit covers the full flight.

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

- [ ] `01-fix-playlist-takeover-attribute` — F1: fix `playlists.py:380` AttributeError
- [ ] `02-constrain-play-file-to-media-root` — F2: AUDIO_MEDIA_ROOT + extension allow-list + disable directory listing
- [ ] `03-validate-audio-port-range` — F3: enforce 8000–8999 at parse time
- [ ] `04-route-say-through-group-members-helper` — F5: `say()` uses `_group_members_of`
- [ ] `05-url-encode-audio-host-filenames` — F12: `urllib.parse.quote` in `url_for`
- [ ] `06-restrict-play-url-schemes` — F14: allow-list `http`/`https` at the tool surface

---

## Post-Flight

### Completion Checklist
- [ ] All 6 legs completed
- [ ] Smoke tests pass against live hardware (basic + playlist)
- [ ] Code merged (single commit on `main`)
- [ ] Maintenance report findings F1, F2, F3, F5, F12, F14 ticked in `missions/01-baseline-maintenance/mission.md`
- [ ] Flight log filled in

### Verification
- `playlist_smoke.py` exercises the takeover branch — log output should include the new clean warning, not an AttributeError trace caught by the outer except.
- Manual: `mcp-sonos` with `AUDIO_PORT=9999` fails at startup with a clear error.
- Manual: `play_file("Kitchen", "/etc/passwd")` returns a validation error, not "success."
- Manual: `play_file("Kitchen", "<file under AUDIO_MEDIA_ROOT>")` works as before.
- Manual: `play_url("Kitchen", "file:///etc/passwd")` returns a validation error.
- Manual: `GET http://<HOST_IP>:<AUDIO_PORT>/` returns 404 instead of an HTML listing.
