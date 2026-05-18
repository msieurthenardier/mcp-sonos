# Leg: 01-fix-doc-traps

**Status**: ready
**Flight**: [Documentation Cleanup](../flight.md)

## Objective
Eliminate the two doc-as-traps: (a) `say` tool docstring advertises gTTS and a `lang` parameter that the Piper backend silently ignores; (b) `playlists.py:4` module docstring claims sessions are keyed by "coordinator UID" — contradicting the actual speaker-UID keying that CLAUDE.md explicitly mandates (Finding F4 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- **Trap A (`server.py:182,184`)**: An MCP agent reading the tool schema sees `description="What to say. Plain text; will be synthesized via gTTS."` and `lang: Field(description="gTTS language code, e.g. 'en', 'fr', 'es'.")`. The backend has been Piper for some time; `tts.py:121-122` documents `lang` as "kept for API parity ... Ignored." An agent will believe `lang="fr"` produces French TTS. It does not — voice is set process-wide via `PIPER_VOICE`. Possible follow-ups: drop the parameter entirely (schema-breaking) or keep it and rename the docstring. Flight design chose docstring fix (least disruptive).
- **Trap B (`playlists.py:4`, `:99`)**: Module docstring says "a worker thread keyed by the resolved *coordinator UID*." Comment at line 99 says `# coord_uid -> session`. But CLAUDE.md lines 70-77 explicitly state the keying is by *speaker UID*, not coordinator UID — and the actual code at `playlists.py:208` (`self._sessions[speaker.uid] = session`) follows the CLAUDE.md invariant. The docs lie. A future contributor reading playlists.py top-down may "fix" the code to match the docs, reintroducing the bug CLAUDE.md was written to prevent.

## Inputs
- `mcp_sonos/server.py:182, 184` (and any nearby say-tool descriptions)
- `mcp_sonos/playlists.py:4` (module docstring) and `:99` (inline comment)
- `mcp_sonos/controller.py:25` (stale `# gTTS at normal speed` comment, if present)

## Outputs
- `say` tool description accurately names Piper and documents that `lang` is ignored (or marked deprecated, kept for backward compat)
- `playlists.py:4` module docstring accurately describes speaker-UID keying matching CLAUDE.md
- `playlists.py:99` comment updated to match

## Acceptance Criteria
- [ ] `say` tool description no longer mentions gTTS
- [ ] `lang` parameter description states it is ignored (or is removed from the tool signature — see decision below)
- [ ] `playlists.py:4` and `:99` describe speaker-UID keying matching the actual code and CLAUDE.md
- [ ] No other stale gTTS references in `mcp_sonos/` (grep verifies)

## Verification Steps
- `grep -rn "gTTS\|gtts" mcp_sonos/` returns no hits (or only intentional historical references in comments, none in agent-facing docstrings).
- `grep -n "coordinator UID\|coord_uid" mcp_sonos/playlists.py` returns no hits.
- Manual: introspect the MCP tool schema (via the inspector or by calling the server) and confirm the `say` description matches reality.

## Implementation Guidance

1. **Decide on `lang` parameter fate**. Flight design says: keep parameter, rewrite description. Sample new text:
   ```python
   text: str = Field(description="What to say. Plain text; synthesized via Piper neural TTS.")
   lang: str = Field(
       default="en",
       description="Deprecated. Ignored. Voice selection is set process-wide via the PIPER_VOICE env var.",
   )
   ```

2. **Rewrite `playlists.py:4` module docstring** to match the speaker-UID keying invariant. Use language that reinforces *why*:
   ```python
   """In-memory playlists with continuous background playback.

   Each active playlist runs a worker thread keyed by the originally-named
   speaker's UID (not the group coordinator's UID). The worker re-resolves
   the group coordinator on every iteration so the playlist follows the
   speaker through grouping changes. Keying by coordinator UID breaks the
   moment someone groups the speaker — see CLAUDE.md for the design history.
   """
   ```

3. **Update `playlists.py:99`** inline comment from `# coord_uid -> session` to `# speaker_uid -> session`.

4. **Search for any other gTTS references** that linger as comments — e.g., `controller.py:25` `# gTTS at normal speed`. Update or drop.

## Files Affected
- `mcp_sonos/server.py` — say tool definition
- `mcp_sonos/playlists.py` — module docstring + inline comment
- `mcp_sonos/controller.py` — any stale gTTS comment

## Edge Cases
- None — text-only changes.

---

## Post-Completion Checklist

- [ ] All acceptance criteria verified
- [ ] Smoke test passes (no behavior change expected)
- [ ] Update `../flight-log.md`
- [ ] Set this leg's status to `completed`
- [ ] Check off in `../flight.md`
