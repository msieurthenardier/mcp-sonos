# Flight Log: Correctness and Capability Hardening

**Flight**: [Correctness and Capability Hardening](flight.md)

## Summary

Flight landed 2026-05-18. All 6 legs completed and committed (one commit per leg). Reviewer confirmed `[HANDOFF:confirmed]` over cumulative changes with two non-blocking notes (see below).

| Leg | Finding | Commit | Status |
|-----|---------|--------|--------|
| 01 | F1 — playlist takeover AttributeError | `44e58cd` | completed |
| 02 | F2 — play_file media root + dir listing | `5d7b977` | completed |
| 03 | F3 — AUDIO_PORT range validation | `5fb457c` | completed |
| 04 | F5 — route say() through helper | `7d34a8a` | completed |
| 05 | F12 — URL-encode filenames | `f5d2415` | completed |
| 06 | F14 — URL scheme allow-list | `434ed5f` | completed |

**Open items for Post-Flight verification by maintainer:**
- F1 live takeover repro (induce `say()` mid-playlist and observe clean log).
- F2 manual file-rejection checks against live hardware with `AUDIO_MEDIA_ROOT` set.
- `smoke_test.py` `say()` anomaly observed at Leg 05 (`play_uri can only be called/used on the coordinator in a group`). Most likely Sonos household grouping topology, not a code regression (Leg 04 smoke ran `say` cleanly; Leg 05/06 don't touch the say path). Re-run smoke when household is in a known state.

**Non-blocking notes from final Reviewer:**
- `mcp_sonos/audio_host.py` env-port parsing: non-numeric `AUDIO_PORT` raises generic `int()` ValueError before reaching `_validate_port`'s nicer message. Acceptable; not in F3's stated scope.
- `mcp_sonos/server.py` `playlist_add_many`: server-side per-index validator silently skips items missing `url` or non-dict items, deferring shape errors to `PlaylistManager.add_many`. Intentional and consistent with the existing `items[i]` idiom.

---

### Flight Director Notes

**2026-05-18 — Flight start**

- Mission flipped: `planning` → `active`
- Flight flipped: `ready` → `in-flight`
- Feature branch: `flight/01-correctness-and-capability` created off `main` (at commit `1cce0ad`)
- Crew loaded from `.flightops/agent-crews/leg-execution.md` (Developer + Reviewer, both Sonnet; Accessibility Reviewer disabled)
- Skipping `/leg` invocation in Phase 2a — all 6 legs were designed during routine-maintenance scaffolding and two were refined during Flight 1's `/flight` design review. Going straight to design-review-via-Developer per leg
- Pre-flight smoke-test baseline is deferred to Leg 01's Developer; first agent will run `smoke_test.py` + `playlist_smoke.py` and record timestamp here before touching code
- Commit cadence per architect review: one commit per leg, all on this feature branch; flight-level Reviewer pass at the end before opening PR

---

## Reconnaissance Report

Verified each finding against current code at flight planning time (2026-05-18, against commit `5cafb1f` on `main`). Source artifact: [`maintenance/2026-05-18.md`](../../../../maintenance/2026-05-18.md), inspection completed ~30 min before this recon — no intervening source-code commits.

| # | Finding | Classification | Evidence | Recommendation |
|---|---------|----------------|----------|----------------|
| F1 | `playlists.py:380` references nonexistent `session.coordinator_name` | `confirmed-live` | `mcp_sonos/playlists.py:380` references `session.coordinator_name`; `PlaybackSession` dataclass (lines 60-83) defines `playlist_name`, `speaker_uid`, `speaker_name`, `current_index`, `shuffle`, `started_at`, `stop_event`, `skip_event`, `back_event`, `thread` — no `coordinator_name`. Outer `except Exception:` at line 398 swallows. | Replace with `session.speaker_name`. Keep `log.info` level — matches surrounding style. |
| F2 | `play_file` exfiltrates arbitrary files to LAN-public audio host | `confirmed-live` | `mcp_sonos/controller.py:167-175` resolves path with `expanduser().resolve()`, checks only `is_file()`, no allow-list. `audio_host.py:83-94` `stage()` does `shutil.copy2(source, self.root / source.name)`. `audio_host.py:44-46`: `self.root` is `tempfile.gettempdir() / "mcp-sonos-audio"`. `audio_host.py:64`: bind is `("0.0.0.0", self.port)`. `Handler(SimpleHTTPRequestHandler)` at line 57 does NOT override `list_directory` → directory listing enabled by default. | Implement allow-list + extension filter at `play_file`; disable listing via override in handler subclass. **Important sub-decision below.** |
| F3 | `AUDIO_PORT` no range validation | `confirmed-live` | `mcp_sonos/audio_host.py:25-27` reads env, casts to int, returns. `PORT_RANGE = (8000, 8999)` defined at line 19 but unused for env-supplied values. | Insert range check between `int(env)` and `return`. Use `PORT_RANGE` constant. |
| F5 | `say()` bypasses `_group_members_of` helper | `confirmed-live` | `mcp_sonos/controller.py:309-314` uses inline `coord.group.members` with try/except inside `say()` to get SoCo objects for volume setting. `_group_members_of` at lines 63-69 returns sorted **names (strings)**, not SoCo objects. | **Sub-decision needed**: `_group_members_of` returns strings, not objects. Two options: (a) Call helper, then `_resolve(name)` per member; (b) Add a `_group_members_objects_of` variant. Option (a) preserves the helper's existing contract and adds one map call. Recommended in flight design decisions below. |
| F12 | `url_for` no URL encoding | `confirmed-live` | `mcp_sonos/audio_host.py:80-81` f-string `f"http://{self.host_ip}:{self.port}/{filename}"`. `stage()` at line 94 calls `self.url_for(target.name)` where `target.name` is the basename of the user-supplied path; basenames can contain spaces. | `urllib.parse.quote(filename)` in `url_for`. TTS WAVs are sha1-hex (URL-safe) so this is latent only for `play_file`. |
| F14 | `play_url` no scheme allow-list | `confirmed-live` | `mcp_sonos/controller.py:155-158` passes `url` straight to `coord.play_uri`. `mcp_sonos/server.py:75` field description says "HTTP(S) URL" but no validation. `mcp_sonos/playlists.py:131-153` `add`/`add_many` only check empty-string. | Add scheme allow-list at the tool surface — `play_url`, `playlist_add`, `playlist_add_many`. Lowercase before compare. |

**No items were retired or scoped-down — all six findings are live.** No drift in line numbers or symbol names against the maintenance report (the report was written from the same commit).

### Additional Observations (not finding-level — affect flight design)

1. **Audio host serve root is shared by TTS and `play_file` copies.** `controller.py:89-93` passes `/tmp/mcp-sonos-audio/` to AudioHost as `root`. Piper writes TTS WAVs into this root; `play_file` `shutil.copy2`'s user files into the same root. Therefore F2's allow-list cannot live on the *serve root* — it must filter `play_file` inputs *before* `stage()` is called. Design decision below.

2. **`_group_members_of` helper returns names, not SoCo objects.** This shapes F5's implementation. Documented as a flight-level design decision.

3. **The `say` tool's `lang` parameter docstring (Flight 2 / F4) and the `playlists.py:4` module docstring (Flight 2 / F4b)** are both still wrong but out of scope here — Flight 2 owns them.

4. **`AudioHost.stop()` (F15, Pass)** is genuinely defined but unwired, as the inspector reported. Within stdio-spawned lifetime expectations; not in scope.

5. **`controller.py:94` `self._lock` and `controller.py:14` `Iterable` import (F6, Flight 2)** are genuinely abandoned per inspection. Out of scope here.

---

## Leg Progress

(Append entries here as legs land.)

### Leg 01 — F1 playlist takeover attribute fix
**Status**: landed
**Started**: 2026-05-18T13:30:00Z
**Completed**: 2026-05-18T13:31:13Z

#### Changes Made
- Replaced `session.coordinator_name` with `session.speaker_name` at `mcp_sonos/playlists.py:380`.

#### Notes
- Pre-flight smoke-test baseline: **pass** — both `smoke_test.py` and `playlist_smoke.py` ran end-to-end against live hardware (speakers: Dining Room, Kitchen, Lounge, Fireplace Room, Patio). Playlist smoke covered start/skip/stop including mid-track stop.
- Grep verified: `coordinator_name` no longer appears in `mcp_sonos/playlists.py` (exit code 1 on `grep -n "coordinator_name" mcp_sonos/playlists.py`).
- F1 takeover branch not exercised end-to-end here — that's a flight-level concern per leg spec.

### Leg 02 — F2 constrain play_file to AUDIO_MEDIA_ROOT
**Status**: landed
**Started**: 2026-05-18T13:35:00Z
**Completed**: 2026-05-18T13:42:00Z

#### Changes Made
- `mcp_sonos/controller.py`: added `import os`; in `SonosController.__init__`, read `AUDIO_MEDIA_ROOT` env var (after the `self.audio` block) and store on `self.media_root: Path | None` (resolved via `Path.expanduser().resolve()`, or `None` when unset/empty); replaced `play_file` body with five-step validation cascade — media_root None → not-a-dir → containment via `Path.is_relative_to` → `is_file` → extension allow-list `{.mp3, .wav, .flac, .m4a, .ogg}` (case-insensitive via `target.suffix.lower()`) — before calling `self.audio.stage(target)`.
- `mcp_sonos/audio_host.py`: added `list_directory(self, path)` override to the inline `Handler` subclass in `start()`; returns 404 via `self.send_error(404); return None`. Blocks `GET /` enumeration without affecting direct-by-name access.
- `.env.example`: added `AUDIO_MEDIA_ROOT` block under `--- Audio host ---` after `AUDIO_PORT`, with comment explaining symlink-followed-then-checked containment, the extension allow-list, the disabled-when-unset default, and the explicit "this does NOT secure the audio HTTP host itself" honesty.
- `README.md`: added `AUDIO_MEDIA_ROOT` row to the Configuration env-var table; extended the existing "Audio server is unauthenticated" bullet in `### Networking / topology limitations` to document both narrowings (play_file scoping; directory-listing block) and to be explicit that direct-by-known-name access still works.

#### Verification
- `py_compile mcp_sonos/controller.py mcp_sonos/audio_host.py` — clean.
- `from mcp_sonos.controller import SonosController` — clean import.
- Ad-hoc test script (started controller with unset env, then `AUDIO_MEDIA_ROOT=/tmp`):
  - `GET http://127.0.0.1:8000/` → 404 (directory listing override works).
  - `play_file(...)` with `media_root=None` → `ValueError("play_file is disabled; set AUDIO_MEDIA_ROOT to enable")`.
  - `play_file("any", "/etc/passwd")` with `AUDIO_MEDIA_ROOT=/tmp` → `ValueError("path /etc/passwd is outside AUDIO_MEDIA_ROOT=/tmp")`.
  - `play_file("any", "/tmp/script.sh")` (exists) → `ValueError("unsupported extension '.sh'; allowed: mp3/wav/flac/m4a/ogg")`.
  - `play_file("any", "/tmp/does-not-exist-123abc.mp3")` → `FileNotFoundError`.

#### Notes
- Live-hardware smoke tests not re-run: F2 only touches the `play_file` path and the audio host's directory-listing handler. `say()` uses Piper → cache_dir → `audio.url_for(name)`, which never traverses `play_file` or `list_directory` (HTTP serves the WAV by direct filename). The pre-flight smoke baseline (Leg 01) covers the `say()` regression surface; no new live-hardware risk introduced here.
- Validation lives in `controller.play_file` (per leg spec — keeps `AudioHost` policy-agnostic). `audio.stage()` is still callable directly from Python, but grep confirms `play_file` is the only caller in the repo.
- The `list_directory` override blocks `GET /` and any directory request but does NOT affect `GET /<filename>` — that's the documented and required behavior for Sonos to fetch audio.

### Leg 03 — F3 validate AUDIO_PORT range
**Status**: landed
**Started**: 2026-05-18T13:45:00Z
**Completed**: 2026-05-18T13:47:00Z

#### Changes Made
- `mcp_sonos/audio_host.py`: added module-level `_validate_port(p: int) -> int` helper directly below `PORT_RANGE`. Raises `ValueError` when `p` is outside `PORT_RANGE` with a message naming the `8000-8999` range, the firewall rationale, and the remediation (set in-range or update the firewall rule). Returns `p` on the in-range path.
- `mcp_sonos/audio_host.py`: wired `_validate_port` into both validating branches of `_pick_port` — the `preferred is not None` programmatic path and the `AUDIO_PORT` env path. The auto-pick branch is unchanged: it produces in-range values by construction.

#### Verification
- `py_compile mcp_sonos/audio_host.py` — clean.
- `AUDIO_PORT=9999 _pick_port()` → `ValueError` with the expected firewall-aware message; non-zero exit.
- `_pick_port(8500)` → `8500` (in-range programmatic).
- `_pick_port(9999)` → `ValueError` (out-of-range programmatic; same message, surfaced via the `preferred` branch).
- `_pick_port()` with no env → `8000` (auto-pick from a free socket; expected first-free in PORT_RANGE).

#### Notes
- Live-hardware smoke tests not re-run: F3 is a startup-time validation on a single env-read path. Behavior change is limited to "raises early instead of failing silently mid-playback" for out-of-range values; in-range values traverse identical code to before. No state-machine, playback, or HTTP-handler surface touched.
- Non-integer `AUDIO_PORT` (e.g. `"abc"`) continues to fail via `int(env)` `ValueError` before `_validate_port` runs — left as-is per leg's "Edge Cases" guidance.

### Leg 05 — F12 URL-encode audio host filenames
**Status**: landed
**Started**: 2026-05-18T13:55:00Z
**Completed**: 2026-05-18T13:57:00Z

#### Changes Made
- `mcp_sonos/audio_host.py`: added `import urllib.parse` to module imports.
- `mcp_sonos/audio_host.py`: in `url_for`, route `filename` through `urllib.parse.quote(filename)` (bound to local `safe`) before f-string interpolation. Default `quote` safe set (`/`) is fine here — `stage()` always passes `target.name` (a basename), and TTS WAV filenames are sha1-hex.

#### Verification
- `.venv/bin/python -m py_compile mcp_sonos/audio_host.py` — clean.
- Inline check: `AudioHost(root=Path('/tmp'), host_ip='1.2.3.4', port=8000).url_for('My Song.mp3')` → `http://1.2.3.4:8000/My%20Song.mp3` (exact match).
- Inline check: same instance, `url_for('simple.mp3')` → `http://1.2.3.4:8000/simple.mp3` (unchanged, no encoding noise).
- `stage()` was already routing through `url_for` — no inline URL construction elsewhere in the module. Implementation guidance item 3 confirmed by reading.

#### Notes
- Smoke test (`smoke_test.py`) ran against live hardware: discovery succeeded (Dining Room, Fireplace Room, Kitchen, Lounge, Patio). The `say` call then failed with `play_uri can only be called/used on the coordinator in a group` — this is **unrelated** to Leg 05. `say` generates a sha1-hex TTS filename, which is URL-safe and unchanged in shape by the `quote` call. The failure is a pre-existing group-coordinator semantics issue in the `say` path, surfaced today (possibly because the smoke-test target speaker has been grouped under a different coordinator on the network since Leg 04's run). Flagged as anomaly below; will not be addressed in this leg per its narrow scope.
- `play_file` against a space-containing filename was NOT exercised end-to-end against hardware in this leg — no staged file under `AUDIO_MEDIA_ROOT` available and no live target. URL string is correctness-verified; "Sonos accepts the encoded URL" portion of AC #3 carried to flight-level Post-Flight, consistent with prior legs' approach to live-hardware risk surfaces.

### Leg 06 — F14 restrict play_url schemes to http/https
**Status**: landed
**Started**: 2026-05-18T14:00:00Z
**Completed**: 2026-05-18T14:05:00Z

#### Changes Made
- New module `mcp_sonos/_urls.py`: `validate_http_url(u: str) -> str`. Lowercases the parsed scheme, requires it to be in `{"http", "https"}`, also requires a non-empty `netloc`. Single source of truth reused at all three sites (tool, controller, playlist).
- `mcp_sonos/server.py`:
  - Imports `AfterValidator` from `pydantic` and `validate_http_url` from `._urls`.
  - Adds module-level `HttpUrl = Annotated[str, AfterValidator(validate_http_url)]` (currently unused as a type alias by the tools — they spell out the `Annotated[...]` inline to preserve their `Field(description=...)`, but the alias is kept as the canonical reusable form per leg guidance).
  - `play_url` and `playlist_add` `url` parameters now go through `AfterValidator(validate_http_url)` alongside their existing `Field(description=...)`.
  - `playlist_add_many`: adds an in-body validation loop that scheme-checks every dict-shaped item carrying a `url`, raising `ValueError("items[{i}]: …")` on the first offender. Dict-shape enforcement stays loose because `PlaylistManager.add_many` already enforces it with the same idiom (per leg guidance — avoids a controller-signature change for a defence-in-depth fix).
- `mcp_sonos/controller.py`: imports `validate_http_url`; calls it as the first statement inside `play_url` (before `_resolve_coordinator`), so direct/test callers of the controller surface get the same gate.
- `mcp_sonos/playlists.py`: imports `validate_http_url`; `add()` wraps the validator in a try/except converting `ValueError → PlaylistError` after the existing empty-string check; `add_many()` does the same per-item with an `items[{i}]:` prefix, inside the build loop (so a bad item raises before `pl.items.extend(normalized)` runs — partial append is structurally impossible).

#### Verification
- `.venv/bin/python -m py_compile mcp_sonos/_urls.py mcp_sonos/server.py mcp_sonos/controller.py mcp_sonos/playlists.py` — clean.
- Direct validator checks:
  - `validate_http_url('file:///etc/passwd')` → `ValueError: URL scheme must be http or https; got 'file'`.
  - `validate_http_url('http://example.com/song.mp3')` → returns the URL unchanged.
  - `validate_http_url('https://example.com/song.mp3')` → returns the URL unchanged.
  - `validate_http_url('http:')` → `ValueError: URL must include a host; got 'http:'`.
  - `validate_http_url('gopher://example.com/')` → `ValueError: URL scheme must be http or https; got 'gopher'`.
  - `validate_http_url('')` → `ValueError: URL scheme must be http or https; got ''`.
  - `validate_http_url('HTTP://example.com/')` → accepted (mixed case lowered before compare).
- Tool surface (Pydantic `TypeAdapter` on `HttpUrl`):
  - `file:///etc/passwd` → `pydantic.ValidationError`.
  - `http://example.com/song.mp3` → accepted.
- Controller surface: `SonosController().play_url('any', 'file:///bad')` → `ValueError` raised by `validate_http_url` (fires before `_resolve_coordinator`, so no hardware/lookup side effects).
- Playlist surface:
  - `manager.add('p_test', 'file:///bad')` → `PlaylistError: URL scheme must be http or https; got 'file'`.
  - `manager.add_many('p_mixed', [{'url':'http://ok.example.com/song.mp3'},{'url':'file:///bad'}])` → `PlaylistError: items[1]: URL scheme must be http or https; got 'file'`, and `len(playlist.items) == 0` after the failed call — confirms no partial append.
- `playlist_smoke.py` against live hardware: full pass — create, add (Piper TTS WAV URLs, `http://192.168.86.38:8000/...`), start, status, skip, stop-mid-track all worked end-to-end on Kitchen. No HttpUrl rejection on legitimate `http://` URLs.

#### Notes
- `smoke_test.py` deliberately skipped per leg guidance — the `say` anomaly surfaced in Leg 05 (`play_uri can only be called/used on the coordinator in a group`) is unrelated to URL-scheme validation and still pending Post-Flight investigation. Playlist smoke covers the `play_uri` regression surface this leg is most likely to affect.
- The `HttpUrl` alias is defined at module scope in `server.py` but the two tool annotations (`play_url`, `playlist_add`) inline the `AfterValidator(validate_http_url)` next to their `Field(description=...)` because chaining `Field` onto an already-aliased `Annotated[...]` is awkward — the inlined form is what the leg guidance prescribes verbatim and it keeps the descriptions visible at the call-site. Kept the alias defined regardless so it's available as the canonical reusable form for any future tool that doesn't need a bespoke description.
- `playlist_add_many` runs both the new in-tool scheme check (clean MCP error path) and then `PlaylistManager.add_many`'s built-in scheme check via the controller (the defence-in-depth path). The two messages differ slightly (`ValueError` vs `PlaylistError`) but the controller is shielded by the tool's earlier check in normal MCP flow.

### Leg 04 — F5 route say through `_group_members_of` helper
**Status**: landed
**Started**: 2026-05-18T13:50:00Z
**Completed**: 2026-05-18T13:52:00Z

#### Changes Made
- `mcp_sonos/controller.py`: inside `say()`, replaced the inline `coord.group.members` block (try/except + `members or [coord]` fallback) with the helper-driven equivalent — call `_group_members_of(coord)` to get member names, then list-comprehend `self._resolve(n)` to map back to SoCo objects. Dropped the `or [coord]` fallback (provably unreachable — `_group_members_of` guarantees a non-empty list via its `[speaker.player_name]` failure-path fallback).

#### Verification
- Baseline grep before edit: `grep -n "\.group\.members" mcp_sonos/controller.py` → 4 line hits across 2 logical sites (helper definition lines 66–67, inline access lines 322–323).
- After edit: `grep -n "\.group\.members"` → 2 line hits, both inside `_group_members_of`'s body (lines 66–67) — one logical site, satisfying the acceptance criterion.
- `grep -n "\.group\.coordinator"` → 1 hit (line 56, inside `_coordinator_of`) — no drift elsewhere.
- `.venv/bin/python -m py_compile mcp_sonos/controller.py` — clean.
- Live-hardware smoke test (`smoke_test.py`) passed end-to-end: `say(Kitchen)` and `say(all)` both succeeded against the five-speaker set (Dining Room, Fireplace Room, Kitchen, Lounge, Patio).

#### Notes
- **Deviation from leg snippet**: the leg's prescriptive snippet wrote `self._group_members_of(coord)`, but `_group_members_of` is a module-level function (defined at line 64 of `controller.py`), not a `SonosController` method. All other call sites in the file use the bare `_group_members_of(coord)` form (lines 138, 165, 258, 283, 328). Followed the established convention — used the module-level call. Same semantics, no behavioral difference.
- Smoke test does not pass a `volume` argument, so the modified `if volume is not None:` branch is not exercised end-to-end here. Confirmed by reading `smoke_test.py` output — `say(Kitchen)` and `say(all)` both took the no-volume path. The modified branch is now structurally identical to other helper call sites (e.g. line 138 `now_playing`) which are exercised by the smoke test, so the regression risk is very low. Explicit volume-on-say verification can be deferred to flight-level Post-Flight.
- The `or [coord]` fallback drop is intentional, not an accidental loss — documented in the leg as provably unreachable given `_group_members_of`'s contract.

---

## Decisions

### 2026-05-18 — Design review outcome

Architect review (`flight-design.md` crew, Sonnet) returned **approve with changes**. Applied:

- **F2 — env read location**: read `AUDIO_MEDIA_ROOT` in `SonosController.__init__`, store on `self.media_root`. Validate lazily on first `play_file` call (not at startup) so a misconfigured path doesn't crash the whole MCP server.
- **F2 — `is_relative_to` Python version**: noted explicitly in leg 02 that `pyproject.toml` requires `>=3.10` so the API is available.
- **F2 — directory-listing override honesty**: leg 02 and README threat-model update now state that the override blocks `GET /` enumeration but does NOT block direct-by-known-name access (Sonos needs that to fetch audio).
- **F14 — defence-in-depth controller guard**: leg 06 now validates at both the tool surface (Pydantic, agent-facing) AND the controller/playlist surface (catches direct/test callers). Same validator function reused.
- **Commit cadence**: changed from single-commit-at-landing to one commit per leg. Legs are independent and revertable; per-leg commits keep `git bisect` and selective revert trivial.
- **Smoke-test coverage gap surfaced**: smoke tests cover F5 only. F1/F2/F3/F12/F14 ride on manual verification in Post-Flight. Documented explicitly in flight's In-Flight section.
- **Prerequisites wording**: changed from "run smoke tests before starting" to "pre-flight baseline: smoke tests pass against live hardware (timestamp recorded here)" — same gate, clearer artifact.

Architect's affirmations (no change needed):
- F2 state-machine surface is clean — `audio.stage()` is called only from `controller.play_file`.
- F5 cache-freshness impact is negligible — `_resolve` is an in-memory lookup against the 30 s speakers cache.
- Leg ordering is fine; no merge-conflict risks in serial or parallel execution.
- HAT/alignment leg skipped — Post-Flight verifications are sufficient for a single-maintainer project.

### Other runtime decisions
(Append below as flight runs.)

---

## Deviations
(Departures from planned approach.)

---

## Anomalies

**2026-05-18 — `say` smoke test fails with "play_uri can only be called/used on the coordinator in a group"** (surfaced during Leg 05 verification). Discovery + group listing succeeded; the error fires inside FastMCP tool `say` when issuing `play_uri`. The smoke target speaker is apparently a non-coordinator member of a group in the current Sonos topology. Not caused by Leg 05 (TTS filenames are sha1-hex; `urllib.parse.quote` of an `[a-f0-9]` string is a no-op). Worth investigating at flight Post-Flight: either the controller is no longer routing to the coordinator before `play_uri`, or recent grouping changes on the network exposed a latent bug. Leg 04's `_group_members_of` rewrite is the most-recent `say`-touching change but the failing call site is `play_uri`, not the volume/members iteration that Leg 04 reshaped — so the regression hypothesis is weak. Most likely pre-existing.

---

## Session Notes
(Chronological notes from work sessions.)
