# Leg: 05-codify-claude-md-patterns

**Status**: completed
**Flight**: [Documentation Cleanup](../flight.md)

## Objective
Append two emergent-from-Flight-01 patterns to the `## When extending` section of `CLAUDE.md`: (a) the `_urls.py` defence-in-depth validator pattern, and (b) the eager-parse/lazy-validate env-var convention (Flight 01 debrief Action Items #2 and #3).

## Context
- Flight 01 introduced `mcp_sonos/_urls.py` — a small module with `validate_http_url` imported and called at the tool surface (Pydantic `AfterValidator`), the controller (`SonosController.play_url`), and the playlist manager (`PlaylistManager.add`/`add_many`). The architect's Flight 01 debrief identified this as "the strongest architectural outcome of the flight" and recommended standardizing it.
- Flight 01 also introduced the `AUDIO_MEDIA_ROOT` env var with a deliberate pattern: parse the env value eagerly in `SonosController.__init__` (resolving to a `Path` or `None`), validate lazily on first `play_file` call (so a misconfigured path doesn't crash the whole MCP server at startup).
- `CLAUDE.md`'s `## When extending` section (line 126) currently captures:
  - New playback feature: add method to controller, thin `@mcp.tool` in server.py
  - Anything touching groups must use `_coordinator_of` and `_group_members_of`
  - New env vars: document in README's Configuration table AND `.env.example`
  - POC scripts are historical
  - README's Roadmap is the punch list
- The new patterns extend that section with two more "if you're about to do X, do Y" bullets.

## Inputs
- `CLAUDE.md` — `## When extending` section starting at line 126
- `mcp_sonos/_urls.py` — the reference implementation of the validator pattern
- `mcp_sonos/controller.py` (post-Flight-01) — `__init__` shows the eager-parse pattern; `play_file` shows the lazy-validate counterpart

## Outputs
- `CLAUDE.md`'s `## When extending` section includes two new entries (bullets or sub-sections) describing the patterns

## Acceptance Criteria
- [x] `CLAUDE.md` `## When extending` section contains a bullet (or sub-section) describing the `_urls.py` defence-in-depth pattern — "single validator module imported at every enforcement surface (tool, controller, manager); validators that gate cross-cutting input policy go in a small `_<topic>.py` module"
- [x] The same section extends or adds a bullet describing the eager-parse/lazy-validate convention — "for env vars whose value can be invalid (paths, ports), parse eagerly at `SonosController.__init__` storing a typed attribute, validate lazily at the first call that uses it; rationale: invalid config doesn't crash the MCP server's startup, the tool returns a clear error instead"
- [x] References to `_urls.py` (and `validate_http_url`) and `AUDIO_MEDIA_ROOT` (as the reference implementation of the lazy-validate pattern) appear with file paths so future contributors can follow the link
- [x] No other CLAUDE.md sections modified (Leg 03 owns the LAN-IP anonymization in `## Important context`)

## Verification Steps
- `grep -n "_urls.py\|defence-in-depth\|defense-in-depth" CLAUDE.md` — at least one hit, inside `## When extending`.
- `grep -n "eager parse\|lazy validate\|AUDIO_MEDIA_ROOT" CLAUDE.md` — at least one hit, inside `## When extending`.
- Visual diff: only `## When extending` changed.

## Implementation Guidance

1. **Read** the current `## When extending` section in `CLAUDE.md` (around lines 126-140) to understand placement, voice, and bullet style.

2. **Append two new bullets** (or sub-sections — match the existing style). Suggested wording (adjust to match voice):

   ```markdown
   - **Cross-cutting input validation (defense-in-depth)** → single validator
     module, imported at every enforcement surface. Example:
     `mcp_sonos/_urls.py::validate_http_url` is imported by `server.py`
     (Pydantic `AfterValidator` at the tool boundary), `controller.py`
     (defensive check in `play_url`), and `playlists.py` (in `add` and
     `add_many`, converted to `PlaylistError`). Same policy enforced at every
     entry surface; agents reading the schema see a clean MCP error, direct
     callers see a `ValueError`/`PlaylistError`. Future candidates for this
     pattern: speaker-name normalization, AUDIO_PORT range, playlist-name
     validation.

   - **Env vars that can be invalid (paths, ports, etc.)** → parse eagerly at
     `SonosController.__init__`, validate lazily at first use. Example:
     `AUDIO_MEDIA_ROOT` is read once at init and resolved into
     `self.media_root: Path | None`; the `is_dir()` check + extension allow-list
     run on every `play_file` call. Rationale: a misconfigured path doesn't
     crash the MCP server at import time — the other 31 tools keep working,
     and the affected tool returns a clear error pointing at the env var.
     Note: this trades startup-fast-fail for graceful degradation; pick
     accordingly per new env var.
   ```

3. **Placement**: append to the END of the `## When extending` section (just before the `## Important context` heading at line 141). This keeps the existing bullets undisturbed.

4. **Match the section's voice**: the existing bullets are short imperatives ("New playback feature → add method..."). The new bullets should follow that style — header in bold, then 2-4 sentences of guidance, then optional reference.

## Files Affected
- `CLAUDE.md` — `## When extending` section only

## Edge Cases
- **Spelling**: use **"defense-in-depth"** (US) per flight design decision. The flight artifact and earlier recon used UK ("defence-in-depth"); reconcile to US throughout this leg's CLAUDE.md additions.
- **If the section grows too long**: consider sub-headers (`### Validator pattern`, `### Env-var pattern`). Not strictly necessary; defer if section length feels fine.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Visual diff confined to `## When extending`
- [x] Update `../flight-log.md` with leg progress entry
- [x] Set this leg's status to `completed`
- [x] Check off this leg in `../flight.md`
