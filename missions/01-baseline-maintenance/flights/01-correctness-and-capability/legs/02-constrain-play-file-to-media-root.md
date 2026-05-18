# Leg: 02-constrain-play-file-to-media-root

**Status**: ready
**Flight**: [Correctness and Capability Hardening](../flight.md)

## Objective
Scope `play_file` to an operator-configured media root, restrict to audio file extensions, and disable directory listing on the audio HTTP host (Finding F2 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- Today, `controller.py:167-175` resolves the agent-supplied path via `expanduser().resolve()` and only checks `is_file()`. `audio_host.py:83-94` `shutil.copy2`'s it into the serve root.
- The audio host is bound `0.0.0.0` and unauthenticated. README explicitly accepts this within the trusted-LAN threat model.
- **What is not accepted**: that a misaligned (e.g., prompt-injected) MCP agent can stage `~/.ssh/id_rsa` or any other readable file onto the LAN-public audio host. This is the one finding from the maintenance report that crosses the documented threat model.
- Architect's recommendation: add `AUDIO_MEDIA_ROOT` env var (default unset → `play_file` disabled), validate resolved paths under the root (using `os.path.realpath` or equivalent), and add an extension allow-list (`.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`). Also disable directory listing on the audio HTTP host.

## Inputs
- `mcp_sonos/controller.py` `play_file` method (around line 167-175)
- `mcp_sonos/audio_host.py` `stage()` method and `SimpleHTTPRequestHandler` subclass
- `README.md` "Configuration (env vars)" table and threat-model paragraph
- `.env.example` (needs the new env var documented)

## Outputs
- `play_file` rejects calls when `AUDIO_MEDIA_ROOT` is unset, with a clear MCP-tool error
- `play_file` rejects paths that resolve outside `AUDIO_MEDIA_ROOT`
- `play_file` rejects paths with extensions outside the allow-list
- Audio HTTP server returns 404 for `GET /` and any directory request, not an HTML listing
- README and `.env.example` updated

## Acceptance Criteria
- [ ] `AUDIO_MEDIA_ROOT` env var read in `audio_host.py` or `controller.py`; if unset, `play_file` returns a validation error pointing at the env var
- [ ] Resolved path (`expanduser().resolve()`) must be under `Path(AUDIO_MEDIA_ROOT).expanduser().resolve()`; otherwise reject with a clear error
- [ ] Extension allow-list: `{.mp3, .wav, .flac, .m4a, .ogg}` (case-insensitive). Other extensions rejected with a clear error
- [ ] `GET http://<HOST_IP>:<AUDIO_PORT>/` returns 404 (or 403); no HTML listing
- [ ] `.env.example` documents `AUDIO_MEDIA_ROOT`
- [ ] README's "Configuration (env vars)" table includes `AUDIO_MEDIA_ROOT`; threat-model paragraph notes that files outside `AUDIO_MEDIA_ROOT` cannot be staged
- [ ] Existing `say()` flow still works (TTS WAVs are written into the audio host's serve root by Piper, not via `play_file` — verify this path is unaffected)

## Verification Steps
- `play_file("Kitchen", "/etc/passwd")` returns a validation error (no copy, no SoCo call).
- `play_file("Kitchen", "~/.ssh/id_rsa")` returns a validation error.
- `play_file("Kitchen", "<AUDIO_MEDIA_ROOT>/song.mp3")` succeeds and plays.
- `play_file("Kitchen", "<AUDIO_MEDIA_ROOT>/script.sh")` returns extension-rejection error.
- `curl http://<HOST_IP>:<AUDIO_PORT>/` returns 404.
- `say("Kitchen", "test")` still works.
- `smoke_test.py` still passes against live hardware.

## Implementation Guidance

1. **Read `AUDIO_MEDIA_ROOT` in `SonosController.__init__`**, store on `self.media_root`. Keeps `AudioHost` ignorant of policy — the env var is consumed by `controller.play_file` and only by `controller.play_file`. Resolve once at construction:
   ```python
   _mr = os.environ.get("AUDIO_MEDIA_ROOT", "").strip()
   self.media_root: Path | None = Path(_mr).expanduser().resolve() if _mr else None
   ```
   `Path.expanduser().resolve()` resolves symlinks too — important for containment-check consistency in step 2. Note: `pyproject.toml` declares `requires-python = ">=3.10"`, so `Path.is_relative_to` (available 3.9+) is safe.

2. **Validate lazily, in `controller.play_file`** (not at startup). Rationale: startup-fail would crash the whole MCP server if the configured path is wrong; lazy-fail keeps the other 31 tools working and gives the caller a clear error.
   ```python
   def play_file(self, name: str, path: str, title: str | None = None) -> dict:
       if self.media_root is None:
           raise ValueError("play_file is disabled; set AUDIO_MEDIA_ROOT to enable")
       if not self.media_root.is_dir():
           raise ValueError(f"AUDIO_MEDIA_ROOT={self.media_root} does not exist or is not a directory")
       target = Path(path).expanduser().resolve()
       if not target.is_relative_to(self.media_root):
           raise ValueError(f"path {target} is outside AUDIO_MEDIA_ROOT={self.media_root}")
       if not target.is_file():
           raise FileNotFoundError(target)
       if target.suffix.lower() not in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}:
           raise ValueError(f"unsupported extension {target.suffix!r}; allowed: mp3/wav/flac/m4a/ogg")
       url = self.audio.stage(target)
       result = self.play_url(name, url, title=title or target.name)
       result["staged_file"] = str(target)
       return result
   ```

3. **Disable directory listing in `audio_host.py`**. The `Handler` subclass already exists at `audio_host.py:57-62` (for `log_message` silencing); extend it:
   ```python
   class Handler(http.server.SimpleHTTPRequestHandler):
       def __init__(self, *a, **kw):
           super().__init__(*a, directory=str(root), **kw)
       def log_message(self, fmt, *args):
           return
       def list_directory(self, path):
           self.send_error(404)
           return None
   ```
   Note: this blocks discoverability (`GET /` returns 404) but does NOT block direct access to known filenames. The serve root continues to serve any file already present by name (TTS WAVs and previously-staged copies). That's intentional — directory listing is the enumeration vector, not the serve-by-name path; the latter is required for Sonos to fetch audio.

4. **Document** in README:
   - Add `AUDIO_MEDIA_ROOT` to the env-var table; describe the default (`unset` → `play_file` disabled) and the rationale (capability scoping).
   - Update the threat-model paragraph in "Limitations / Networking / topology": note that `play_file` cannot stage files outside `AUDIO_MEDIA_ROOT`, AND that the audio HTTP host *still* serves any file already inside the serve root (TTS WAVs, previously-staged files) to any LAN listener who knows or guesses the filename. Disabling directory listing removes discoverability, not access-by-known-name.

5. **Document** in `.env.example` with a comment explaining the security rationale and the symlink-followed-then-checked behavior.

## Files Affected
- `mcp_sonos/controller.py` — `play_file` method
- `mcp_sonos/audio_host.py` — new handler subclass; possibly `AUDIO_MEDIA_ROOT` env read
- `.env.example` — new variable
- `README.md` — env-var table + threat-model paragraph

## Edge Cases
- **Symlinks**: `Path.resolve()` follows symlinks on both the supplied path and `AUDIO_MEDIA_ROOT`. The containment check operates on realpaths. Document in `.env.example`: "symlinks are followed before the containment check; a symlink under AUDIO_MEDIA_ROOT pointing outside will be rejected."
- **`AUDIO_MEDIA_ROOT` set to a non-existent path**: fail on the first `play_file` call with a clear error, NOT at startup. The MCP server stays up; the other 31 tools keep working.
- **Case-insensitive extension match**: `target.suffix.lower()` covers `.MP3` etc.
- **TTS WAVs**: Piper writes into the audio cache dir (`/tmp/mcp-sonos-audio/`), which is the server's serve root — independent of `AUDIO_MEDIA_ROOT`. `say()` is unaffected because TTS doesn't route through `play_file`. The two roots remain separate by design.
- **Directory listing override does NOT block known-filename access**: `GET /tts-cache-file.wav` will still succeed for any file present in the serve root. That's required for Sonos to fetch audio. The override only blocks `GET /` enumeration. Document this honestly in the README threat-model paragraph (step 4 above).
- **`controller.audio.stage()` direct calls**: confirmed clean. Grep shows `stage()` is only called from `controller.play_file`. After this leg lands, the validation site (`play_file`) is the only call site that reaches `stage()`, closing the surface completely.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes
- [ ] README and `.env.example` updated
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
