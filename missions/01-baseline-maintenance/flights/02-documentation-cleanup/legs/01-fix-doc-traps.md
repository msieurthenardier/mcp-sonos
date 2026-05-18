# Leg: 01-fix-doc-traps

**Status**: completed
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
- [x] `say` tool description (`server.py`) no longer mentions gTTS
- [x] `lang` parameter description states it is ignored (parameter kept for backwards-compat per flight design decision)
- [x] `playlists.py:4` module docstring describes **speaker-UID keying** matching the actual code and CLAUDE.md
- [x] `playlists.py:99` inline comment updated from `# coord_uid -> session` to `# speaker_uid -> session`
- [x] `controller.py` stale comment "# gTTS at normal speed is ~150 wpm" (around line 27) updated to name Piper (or rewritten)
- [x] No **agent-facing** gTTS references remain. Internal historical comments referencing the gTTS→Piper migration are acceptable IF they're accurate (e.g., `tts.py` `# 'lang' kept for API parity with the old gTTS-based synthesize.` is fine — it documents the why)

## Verification Steps
- `grep -rn "gTTS\|gtts" mcp_sonos/` — review hits manually. Acceptable: `tts.py` historical-migration-rationale comments. Not acceptable: any hit in `server.py` (agent-facing) or `controller.py` (stale `# gTTS at normal speed`).
- `grep -n "coord_uid\|coordinator UID" mcp_sonos/playlists.py` returns no hits. (The `resolve_coordinator` callable name and the helper's "coordinator" concept are distinct from the keying claim and may appear in legitimate prose elsewhere — only the keying claim is wrong.)
- Manual: introspect the MCP tool schema (via the inspector or by calling the server) and confirm the `say` description matches reality.

**Schema-contract note**: changing the `lang` Field description does alter the MCP tool schema exposed to agents (the description text). Not a behavior change — just a documentation-honesty change. Agents that were ignoring the parameter continue to ignore it; agents that were honoring "gTTS language code" should now see "deprecated / ignored" and stop relying on it.

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
- `mcp_sonos/server.py` — `say` tool definition (line numbers shifted from maintenance report — find via grep; the relevant lines are the `Field` descriptions on `text` and `lang` parameters of the `say` tool)
- `mcp_sonos/playlists.py` — module docstring (lines 1-11) + inline comment around line 99
- `mcp_sonos/controller.py` — stale `# gTTS at normal speed` comment (around line 27)
- `mcp_sonos/tts.py` — **no change**, but verify the existing historical comment about the migration is accurate; it should stay

## Edge Cases
- None — text-only changes.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Smoke test passes (no behavior change expected)
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
