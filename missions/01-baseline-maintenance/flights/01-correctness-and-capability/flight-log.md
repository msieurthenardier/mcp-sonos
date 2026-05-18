# Flight Log: Correctness and Capability Hardening

**Flight**: [Correctness and Capability Hardening](flight.md)

## Summary
(Filled in during execution.)

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
(Unexpected issues encountered.)

---

## Session Notes
(Chronological notes from work sessions.)
