# Flight Log: DJ Voice Segments in Playlists

**Flight**: [DJ Voice Segments in Playlists](flight.md)

## Summary
Sortie 01 chartered and flown 2026-10-10 (autonomous overnight run). Both legs completed; unit suite 177 → 213; `dj` hardware smoke PASS on Kitchen. Released as 0.6.0.

---

## Leg Progress

### voice-items
**Status**: landed
**Started**: 2026-10-10
**Completed**: 2026-10-10

**Changes Made**
- `mcp_sonos/playlists.py`: `PlaylistItem.text`/`kind`; `MAX_VOICE_TEXT_CHARS`; shared `_normalize_item` + `_build_items` (validate all, synthesize outside the lock, append under it); `synthesize_voice` DI; `PlaybackSession.order`/`scheduled_ids`/`current_item` built in the registering lock block; worker reworked to the addendum's locked `while True` loop (extend-or-deregister, identity removed-skip, `current_item`); back handler scans for nearest present earlier item (DD-10); `status()` adds `current_playlist_index`; module docstring.
- `mcp_sonos/controller.py`: `_synthesize_voice_url` wired into `PlaylistManager`.
- `mcp_sonos/server.py`: `playlist_add` (`url` optional, `text`), `playlist_add_many` docs and up-front loop; playlist-section comment corrected.
- `tests/test_playlist_voice_items.py` (36 new tests), `tests/_fakes.py` (`play_uri_log`), `tests/test_version.py` (0.6.0).
- `playlist_smoke.py dj` scenario; README, CLAUDE.md; `__version__ = "0.6.0"`.
- Suite: 177 -> 213 passed, 3 consecutive runs clean.

**Notes**
- Worker-thread tests that need the worker engine use MCP-hosted track URLs (`http://192.168.1.50:8000/...`); all-external URLs correctly route to the native queue.
- The dj scenario uses `playlist_next` to skip past the long first/last song so the voice items are reached quickly; it asserts `now_playing` PLAYING with `uri == current_item.url` during each voice item. Not run against hardware (leg 2). A voice clip shorter than the 0.2 s poll could cause a false timeout.

### hardware-dj-run
**Status**: landed
**Started**: 2026-10-10
**Completed**: 2026-10-10

**Changes Made**
- None. No code changes were needed.

**Hardware run**
- Probe: Kitchen found, standalone coordinator, STOPPED, volume 22 (recorded pre-run).
- Attempt 1 (of max 3): `SMOKE_SPEAKER=Kitchen SMOKE_VOLUME=10 timeout 600 .venv/bin/python playlist_smoke.py dj` -> exit 0, "DJ smoke: PASS". Log: scratchpad `dj-smoke-1.log` (outside repo).
- Observed: engine `worker`; voice item 'DJ: That was the first track...' became `current_item` with `now_playing` PLAYING at its hosted URI (asserted by the harness against `current_item.url`); advanced to 'SoundHelix Song 2'; live-appended voice item 'DJ: And that was the last track. Goodnight.' became current and played.
- After: Kitchen volume 22 (equals pre-run), transport STOPPED, standalone. No manual restore needed.
- Operator's audible listening check remains for the morning.

---

## Decisions

---

## Deviations

- `tests/test_version.py` asserted `0.5.0`; updated to `0.6.0` with the bump (not listed in the leg's Files Affected).
- Leg said `playlist_smoke.py` `build_playlist` uses `select_track_pool`; it does not (it synthesizes TTS clips). The dj scenario calls `select_track_pool` directly.

---

## Anomalies

- Harmless harness noise: the scenario's pre-clean `playlist_delete smoke-dj` logs a `PlaylistError: No playlist named` traceback (rich-formatted) at the start of output before the run; not a failure.

---

## Session Notes

### 2026-10-10 — Planning
- Charter agreed by operator. Reap constraint accepted: voice playlists run on
  the worker engine and stop if the MCP process exits.
- Crew interview: `text` field on items (no new tool); eager synthesis at add
  time; live-append fix pulled into scope; verification = unit suite + `dj`
  smoke scenario only (no HAT, no behavior-test spec).
- Operator reversed the draft DD-6: shuffle is the agent's choice, voice items
  shuffle like any item.
- Architect review cycle 1: approve with changes. Folded in DD-9 (shuffled
  status index), DD-5 rework (`scheduled_count`, locked exit), DD-10
  (previous-at-0), DD-1 normalization + Pydantic nested-Annotated shape,
  takeover-premise note, tightened cache contracts.
- Operator authorized a fully autonomous overnight run: implement, merge, and
  cut a minor release (0.6.0). Hardware leg runs unattended at low volume;
  audible confirmation deferred to the operator's morning check-in.
- Architect review cycle 2 (cap reached): approve with changes, no deadlock
  found. Applied: `scheduled_count` on the session, initialized from
  `len(order)` and adjusted by `remove`/`clear`; locked item snapshot; both
  session pops keep the `cur is session` guard; DD-10 corrected to
  `max(-1, idx - 2)` (index 1 was also wrong); `current_playlist_index`
  defaults to `start_index`; keyword-only `text`/`title` on `add`; stale
  DD-3/DD-8 text fixed. Remaining items resolved by the Flight Director under
  the operator's autonomous-run authorization (no third cycle).
- Gate re-check: one decision cluster, two legs — still a sortie. Status → ready.

### Flight Director Notes
- 2026-10-10: Loaded `.flightops/agent-crews/leg-execution.md` (valid
  structure). Branch `sortie/01-dj-voice-segments` created from `main`
  (58c2bc1). Baseline suite: 177 passed. Sortie → in-flight.
- Leg 1 `voice-items` designed. Risk tier **high**: worker concurrency and
  session-lifecycle changes (DD-5), shared tool interface change
  (`playlist_add` url optional), and pre-existing behavior reversed
  (DD-9/DD-10). Running a Developer design review.
- Leg 1 design review (Developer): approve with changes. **High:** the
  index + `scheduled_count` live-append design double-plays an item appended
  after a `remove` (a shifted index is indistinguishable from a new one).
  **Decision:** switch DD-5/DD-9 to identity-based scheduling (`order` holds
  `PlaylistItem` refs, `scheduled_ids` by `id()`, removed items skipped by
  identity, `session.current_item`); `remove`/`clear` need no bookkeeping.
  Flight spec DD-5/DD-9 revised in place with an in-flight revision note
  (permitted while in-flight; recorded here). Also folded in: required
  `SoCoFake.play_uri_log` plus a test-local gated fake for deterministic
  worker tests; session built and registered in one locked block; AC5 must
  construct `PlaylistManager` directly (the `stub_controller` fixture's
  `url_for` would route to the native queue); AC10 test recipe; AC7 (b)
  skip-race and (f) `playlist_from_page` pattern tests.
- The identity-scheduling switch is substantive, so a second
  leg-design review cycle is running (cycle 2 of 2).
- Leg 1 design review cycle 2: approve with changes. Applied as a binding
  "Design Review Addendum": a while-loop order in the locked block (so a
  removed tail re-triggers extend-or-exit), a backward scan for previous onto
  a removed item, a title fallback by play-order position, `first_item`
  taken under the lock, `status()` after delete, and test-determinism
  notes. Leg 1 → ready. Spawning the Developer to implement.

### Flight Director Notes (cont.)
- Leg 1 `voice-items` → `[LAND:leg]`. FD re-ran the suite (213 passed) and
  confirmed the working tree contains only the expected changes; stray files
  untouched.
- Leg 2 `hardware-dj-run` designed. Risk tier **low**: no planned code
  change; it runs an existing harness at low volume on a standalone speaker
  (Kitchen, volume 22 at planning). Any fix it needs is reviewed by the
  flight-end Reviewer. No leg design review. Spawning a Developer.
- Leg 2 `hardware-dj-run` → `[LAND:leg]`. FD checked `dj-smoke-1.log`
  (scratchpad, not committed): engine `worker`, "voice item observed playing"
  and "appended voice item observed" both pass through the
  `observe_playing=True` path (`now_playing` PLAYING with `uri == item.url`),
  ending "DJ smoke: PASS". All autonomous legs are landed. Spawning the
  flight-end Reviewer (Sonnet).
- Flight-end Reviewer: `[HANDOFF:confirmed]`, no blocking issues (213
  passed; the new test file passed 3 times). Non-blocking: tick the flight
  checkboxes at close (done); a voice clip shorter than the 0.2 s smoke poll
  could falsely time out the `dj` harness (harness-only; accepted).
- Legs → completed. Flight → landed. Charter criterion 2 is hardware-verified;
  the operator's audible check is still pending.
- Commit made by the FD directly rather than by a spawned Developer
  (a mechanical commit with no source edits; saves one spawn under a tight
  usage window). Files were staged explicitly so the operator's stray root
  files (`play`, `play-`, `song-`, `voice`) stay out.
