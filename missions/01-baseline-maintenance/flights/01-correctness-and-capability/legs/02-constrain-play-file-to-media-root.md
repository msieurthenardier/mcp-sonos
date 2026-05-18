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

1. **Read `AUDIO_MEDIA_ROOT` from env**. Place the read where other env vars live (likely top of `audio_host.py` or in a config helper). Resolve once at startup: `media_root = Path(env_value).expanduser().resolve() if env_value else None`.

2. **In `controller.py` `play_file`**:
   - If `media_root is None`: return validation error "play_file is disabled; set AUDIO_MEDIA_ROOT to enable".
   - Resolve the supplied path: `target = Path(path).expanduser().resolve()`.
   - Check containment: `target` must be `media_root` or under it. Use `target.is_relative_to(media_root)` (Python 3.9+).
   - Check `target.is_file()` (existing logic).
   - Check `target.suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg"}`.
   - On any failure, raise a clear `ValueError` or return an MCP-shaped error response (match the surrounding error style in the file).

3. **Disable directory listing in `audio_host.py`**:
   - Subclass `SimpleHTTPRequestHandler`; override `list_directory(self, path)` to return a 404 response (use `self.send_error(404)`).
   - Apply the new handler class to the `HTTPServer` constructor.

4. **Document** in README:
   - Add `AUDIO_MEDIA_ROOT` to the env-var table; describe the default (`unset` → `play_file` disabled) and the rationale (capability scoping).
   - Update the threat-model paragraph (in "Limitations / Networking / topology") to note the new contract: `play_file` cannot stage files outside `AUDIO_MEDIA_ROOT`.

5. **Document** in `.env.example` with a comment explaining the security rationale.

## Files Affected
- `mcp_sonos/controller.py` — `play_file` method
- `mcp_sonos/audio_host.py` — new handler subclass; possibly `AUDIO_MEDIA_ROOT` env read
- `.env.example` — new variable
- `README.md` — env-var table + threat-model paragraph

## Edge Cases
- **Symlinks**: `Path.resolve()` follows symlinks, so the realpath is what's compared. Document this in `.env.example` ("symlinks are followed before the containment check").
- **`AUDIO_MEDIA_ROOT` set to a path that doesn't exist**: fail at startup with a clear error rather than silently disabling `play_file`.
- **Case-insensitive extension match**: `target.suffix.lower()` covers `.MP3` etc.
- **TTS WAVs**: Piper writes into the audio cache dir (`/tmp/mcp-sonos-audio/`), which is the server's serve root — independent of `AUDIO_MEDIA_ROOT`. Verify `say()` is unaffected. If both should be served from the same root, that's a bigger refactor — keep them separate for this leg.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes
- [ ] README and `.env.example` updated
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
