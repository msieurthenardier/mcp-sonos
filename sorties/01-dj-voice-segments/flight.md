# Sortie: DJ Voice Segments in Playlists

**Status**: completed

## Charter

### Outcome
When building a playlist, the agent can insert a spoken "DJ" segment (plain
text, synthesized server-side) at any position, and `playlist_play` plays
songs and voice segments in order on the target set — e.g. song → song →
song → voice → song → … — with no further agent calls.

### Why Now
Enables a curated listening experience: the agent picks the music *and*
introduces it. Today the agent can only interject via `say`, which preempts
playback and has no way to know when a song ends; the playlist pipeline
already routes MCP-hosted audio (TTS output) to the worker engine, so the
step is small.

### Success Criteria
- [x] A single `playlist_add_many` call can mix URL items and text items;
      text items keep their position and show as voice items in `playlist_get`.
- [x] `playlist_play` on a mixed playlist plays every item in order on real
      hardware, with voice segments audible between songs. *(Hardware
      verified 2026-10-10: `dj` smoke PASS on Kitchen, `now_playing` PLAYING
      at each voice item's hosted URI. Operator confirmed audibly
      2026-10-11.)*
- [x] `playlist_next` / `playlist_previous` / `playlist_stop` /
      `playlist_status` behave the same across voice items as song items.
- [x] Unit tests cover the new item type, and the README agent system
      prompt documents the DJ pattern.

### Constraints
- No new dependencies — reuse Piper TTS (`tts.synthesize`) and the existing
  audio host.
- Existing URL-only playlist behavior is unchanged (all-external playlists
  still route to the native queue and survive a reap).
- Accepted: a playlist containing any voice segment runs on the worker
  engine and stops if the MCP process exits (operator-confirmed 2026-10-10).

---

## Pre-Flight

### Objective
Add a second playlist item kind — a **voice item**, created from plain text —
alongside today's URL tracks. `playlist_add` and `playlist_add_many` accept
`text` in place of `url`; the text is synthesized immediately with Piper and
stored as an MCP-hosted URL, so the existing routing (`any_mcp_hosted` →
worker engine) and the existing worker loop play songs and voice segments in
order with no new playback machinery. In the same pass, fix the worker so
items appended to a playlist *while it plays* are actually played — today the
play order is frozen at start, contradicting README rule 11 and defeating a DJ
who adds commentary as the set unfolds.

### Open Questions
- [x] How does the agent add a voice item? → DD-1
- [x] When is speech synthesized? → DD-2
- [x] Must voice playlists survive a reap? → No (charter constraint, DD-3)
- [x] Fix the frozen play order here or as a squawk? → Here (DD-5)
- [x] What does shuffle do with voice items? → Allowed; agent's choice (DD-6)
- [x] How is the hardware criterion verified? → Smoke script only, no HAT (DD-8)

### Design Decisions

**DD-1 — Item shape: `text` as an alternative to `url`, no new tool.**
`PlaylistItem` gains `text: Optional[str] = None`. An item is a *track*
(`url` given) or a *voice* item (`text` given) — exactly one, never both,
never neither. `playlist_add(name, url=None, text=None, title=None)` and each
`playlist_add_many` dict accept the same either/or. `to_dict()` adds
`"kind": "track" | "voice"` to every item, and `"text"` for voice items
(voice items still carry `url` — the hosted URL — so existing readers keep
working).
- Rationale: an agent writes a whole curated set (song, song, song, voice, …)
  in **one** `playlist_add_many` call, positions implicit; no new tool to
  discover, and no insert-position API.
- Trade-off: `playlist_add`'s `url` becomes optional, so the "exactly one of"
  rule is enforced in code rather than by the schema shape. `kind` is an
  additive key on an existing response shape.
- **Normalization rules** (one private normalizer, used by both add paths):
  a `url` or `text` that is `None`, missing, or empty/whitespace-only after
  `.strip()` counts as **absent** (fixes today's `str(None) → "None"` hazard
  in `add_many`). `url`, `text`, and `title` must be `str` when present,
  otherwise `PlaylistError` naming the index. `text` is stored stripped.
  Over-cap text (DD-4) is a hard error, never truncated.
- **Server schema shape**: Pydantic v2 runs an `AfterValidator` on the whole
  `str | None` union, including `None`, so the validator must sit on the
  inner type:
  `url: Annotated[Annotated[str, AfterValidator(validate_http_url)] | None, Field(...)] = None`.
  `playlist_add_many`'s up-front url loop (`server.py` ~L363) skips items
  whose `url` is absent per the rules above. The manager re-validates
  (defense-in-depth, per CLAUDE.md).

**DD-2 — Synthesize eagerly at add time, via an injected callable.**
`PlaylistManager.__init__` gains `synthesize_voice: Optional[Callable[[str], str]] = None`
(text → hosted URL). `SonosController` wires it to
`self.audio.url_for(synthesize(text, self.cache_dir).name)` — the exact
pipeline `say` uses. When it is `None` (bare test construction), adding a
voice item raises `PlaylistError` naming the missing capability. Synthesis
runs **outside** `self._lock`. `add_many` validates *every* item first
(shape, url scheme, text non-empty and ≤ `MAX_VOICE_TEXT_CHARS`), then
synthesizes, then appends all under the lock — so a bad item anywhere fails
the call before any synthesis and nothing is half-appended. Synthesis
failures (e.g. Piper voice download) are re-raised as `PlaylistError` with
the cause chained.
- Rationale: errors surface at build time, while the agent is still
  curating; playback starts instantly with no per-segment synthesis gap;
  follows the project's DI pattern (`resolve_coordinator`,
  `invalidate_speakers_cache`) so `playlists.py` stays free of `tts`/
  `audio_host` imports and testable with a fake.
- Trade-off: `playlist_add_many` with several voice items blocks ~1 s per
  uncached segment (plus ~2 s first-voice load per process). Identical text
  re-uses the TTS cache.

**DD-3 — Routing is unchanged; voice playlists run on the worker engine.**
A voice item's URL is `http://{host_ip}:{audio_port}/tts_….wav`, which
`any_mcp_hosted` already classifies as MCP-hosted → worker engine. No change
to `play()`'s routing. All-external (track-only) playlists still go to the
native queue.
- Rationale: charter constraint — operator accepted that voice playlists stop
  if the MCP process exits. The hosted URL is only reachable while this
  process's audio host runs, and playlists are in-memory with the same
  lifetime, so the URL's host/port can't go stale within a process (the
  backing file can still vanish if tempdir is cleaned — see Cache Freshness).
- Trade-off: no reap survival for DJ sets. A track-only playlist already
  playing on the native queue does **not** pick up a voice item appended
  later (the hardware queue was loaded at start) — documented, not fixed.

**DD-4 — Voice text cap: `MAX_VOICE_TEXT_CHARS = 1000`.**
Module constant in `playlists.py`, enforced in the manager (both add paths)
and surfaced in the tool's parameter description.
- Rationale: DJ segments are short; the cap bounds per-item synthesis time
  and stops an agent from accidentally pasting a page into a voice item.
- Trade-off: arbitrary; long-form narration should use `say`.

**DD-5 — Live append on the worker engine (identity-based scheduling).**
*(Revised in-flight 2026-10-10 after the leg-1 design review — the earlier
index + `scheduled_count` design could double-play an item appended after a
`remove`, because a shifted index is indistinguishable from a new one. See
flight log.)*
The worker schedules **item objects, not indices**. `PlaybackSession` holds
`order: list[PlaylistItem]` (object references, permuted when shuffled) and
`scheduled_ids: set[int]` (`id()` of every item ever placed in `order` —
stable because `order` keeps the objects alive). Both are built, together
with the rest of the session, **inside the same `self._lock` block that
registers the session** in `_play_via_worker`. At the top of each outer
iteration the worker takes `self._lock` once and:
- if `current_index >= len(order)`: appends to `order` every item in
  `playlist.items` whose `id()` is not in `scheduled_ids` (insertion order),
  recording their ids; if none were added, deregisters the session (guarded
  by `cur is session`) and exits;
- snapshots `item = order[current_index]`; if `item` is no longer in
  `playlist.items` (identity check — it was removed or the playlist was
  cleared), advances `current_index` and re-checks within the same block
  rather than playing it;
- records `session.current_item = item`;
then releases the lock before `play_uri`. Because `add`/`add_many` append
under the same lock, an append lands either before the final check (played
exactly once) or after the session is gone (the agent must `playlist_play`
again). `remove`/`clear` need **no** session bookkeeping. Consequences:
`playlist_from_page`'s clear-then-add_many during playback lets the current
item finish, skips the old items, then plays the new page list once.

Locking rules for the worker's block: it touches only `playlist.items`, the
session, and `self._sessions` directly — it must **not** call
`_get_playlist`, `_session_for`, `has_active_session`, or anything else that
takes `self._lock` (non-reentrant). Both session pops — the locked exit and
the existing `finally` — keep the `cur is session` guard; `finally` remains
the fallback for the break/crash/stop paths.
- Rationale: makes README rule 11 true, and lets the DJ append commentary
  (and more songs) while the set plays.
- Trade-off: appended items always play in insertion order, even in a
  shuffled session. Appending after the worker has already exited starts nothing; the
  agent must call `playlist_play` again (README rule 11 and the `server.py`
  playlist-section comment are corrected to say so). `playlist_remove`/`clear`
  during playback are now handled by identity (removed items are
  skipped; nothing double-plays) — this also retires the pre-existing
  index-shift hazard. A track-only playlist already
  playing on the native queue never picks up appends (README says so).

**DD-6 — Shuffle is the agent's choice; voice items shuffle like any item.**
No special-casing: `shuffle=True` on a playlist containing voice items
permutes all items, voice included. (Operator decision 2026-10-10: a voice
item isn't necessarily DJ commentary — the onus is on the agent to pick the
right option.) README's agent prompt notes that shuffle scatters voice items,
so a DJ set should play unshuffled.
- Rationale: keeps the item kinds symmetric and the tool contract simple; the
  manager doesn't guess intent.
- Trade-off: an agent that shuffles a DJ set gets commentary out of context —
  mitigated by documentation, not code.

**DD-7 — Display title default.** A voice item with no `title` gets
`DJ: <first 40 chars of text>` (mirrors `say`'s `Say: {text[:40]}`) — used
for `play_uri`'s title and `to_dict()`.

**DD-8 — Verification: unit suite + a `dj` scenario in `playlist_smoke.py`.**
No behavior-test spec and no HAT leg (operator decision). Hardware
verification is a new smoke scenario that builds track → voice → track,
plays it, and polls `playlist_status` to observe the current item advancing
through the voice item to the next track — asserting that while the voice
item is current, `now_playing` reports `PLAYING` with `uri == item.url`
(guards the short-clip risk below) — then appends a voice item live and
observes it play. Selected by argv (`playlist_smoke.py dj`); the default
no-arg run is unchanged. The operator's listening check happens at the morning check-in
(the hardware leg runs unattended, at low volume).
- Apparatus premise audit — **act**: the FastMCP in-process `Client` drives
  `playlist_add_many` / `playlist_play` / `playlist_next` / `playlist_stop`
  exactly as the agent does (existing pattern in `playlist_smoke.py`).
  **Observe**: worker-engine `playlist_status` returns `current_index` and
  `current_item` (`playlists.py:status`, resolved via `session.current_item`
  after DD-9 — today it reads `pl.items[sess.current_index]`, the DD-9 bug),
  which will carry `kind`/`text` after DD-1; `now_playing` returns the live
  coordinator `uri` (`controller._track_state`) to cross-check that Sonos is
  actually playing the hosted WAV, not just that the worker advanced.
- Trade-off: "audible" is confirmed by the operator's ear during the run,
  not by an independent Validator.
- **Takeover-detection premise** (worker compares `current_track_info().uri`
  to `item.url`, `playlists.py` ~L394): low risk. Voice URLs come from
  `AudioHost.url_for` with names `tts_<hex16>.wav` — nothing to
  percent-encode — and the stored `item.url` is byte-identical to what
  `play_uri` receives; hosted-WAV worker playback already ships (`play_file`
  playlists). Residual risk is a *short* clip finishing before `PLAYING` is
  ever observed (`STOPPED_CONFIRMATIONS=2` at 0.5 s), which would end the
  item early rather than misfire takeover — hence the smoke assertion above.

**DD-9 — Session tracks the real current item (fixes shuffled status).**
Pre-existing defect surfaced by the design review and made blocking by DD-6:
under shuffle, `session.current_index` indexes `order`, but
`PlaylistManager.status()` reads `pl.items[sess.current_index]`, so
`current_item` is wrong for every shuffled worker session. Fix (with DD-5's
identity scheduling): the worker records `session.current_item` (the object)
when it starts an item; initial value is the start item. `status()` reports
`current_item` from it, and `current_playlist_index` computed by identity
search in `pl.items` under the lock (`-1` if the item has since been
removed). `to_dict()` keeps `current_index` meaning *position in play order*
(unchanged contract) and never resolves items itself.
- Rationale: criterion 3 and DD-8 both observe `current_item`; shuffle with
  voice is now a supported combination.
- Trade-off: one more field on the session/status shape (additive).

**DD-10 — Fix "previous" at the first item.** Pre-existing: the back
handler does `max(0, idx - 2)` then the outer `+1`, so `previous` at index 0
moves *forward* to index 1, and at index 1 it replays index 1 instead of
going to index 0 (the `< 0` branch is dead). Fix:
`session.current_index = max(-1, session.current_index - 2)` so after the
outer `+1` back at 0 replays 0 and back at N goes to N-1. Test idx 0 and 1. Same loop DD-5 edits, so it rides along. Documented
semantic: `previous` follows play order, so from the song after a voice item
it replays the voice item; under shuffle it goes to the previous item in the
shuffled order.

### Prerequisites
- [x] Piper TTS + audio host working (`say` in production use).
- [x] Worker engine plays MCP-hosted WAV/MP3 via `play_uri` (existing
      `play_file`-staged and mixed-playlist path).
- [x] Sonos household reachable from this host for leg 2 (operator confirms
      at leg start; `discovery_smoke.py --runs 1` as the probe).
- [x] Windows Firewall rule "WSL-Sonos-Audio" (TCP 8000-8999) still in place
      — without it voice items go `TRANSITIONING → STOPPED` silently.

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [x] Prerequisites verified (hardware items at leg 2 start)
- [x] Validation approach defined
- [x] Legs defined

---

## In-Flight

### Technical Approach

1. **`mcp_sonos/playlists.py`**
   - `PlaylistItem`: add `text: Optional[str] = None`; `kind` property;
     `to_dict()` adds `kind` (+ `text` for voice).
   - `MAX_VOICE_TEXT_CHARS = 1000`; a single private normalizer
     (`_normalize_item(url, text, title, *, where)`) used by `add` and
     `add_many` that enforces exactly-one-of, url validation, text
     non-empty/cap — returning a pending spec that still needs synthesis.
   - `__init__`: `synthesize_voice` DI param (default `None`).
   - `add` / `add_many`: validate all → synthesize voice items outside the
     lock (wrap failures as `PlaylistError`) → append under the lock.
   - `_worker` / `_play_via_worker`: identity-based `order` +
     `scheduled_ids`, built inside the registering lock block; one locked
     block per iteration for extend-or-exit, removed-item skip, and
     `current_item` (DD-5, DD-9); back-at-0/1 fix (DD-10).
   - `status()`: `current_item` / `current_playlist_index` from
     `session.current_item` (DD-9).
   - `add()` signature: `add(name, url=None, *, text=None, title=None)` so a
     positional third argument can never bind to `text`.
   - Title default for voice items (DD-7) via the item, not the worker's
     `f"{playlist} #{n}"` fallback.
   - Module docstring: mention item kinds and live append.
2. **`mcp_sonos/controller.py`**: wire `synthesize_voice` into the
   `PlaylistManager(...)` construction. No business logic in `server.py`.
3. **`mcp_sonos/server.py`**: `playlist_add` — `url` optional (validator
   applied only when present), new optional `text` with a description
   pointing at the DJ pattern and the cap; `playlist_add_many` description
   documents `{"text": ...}` items; its up-front url validation skips text
   items. Docstrings note that voice items make the playlist use the worker
   engine.
4. **Tests** (`tests/test_playlist_voice_items.py`, new; reuse `SoCoFake`):
   add/add_many with a fake synthesizer (order preserved, `kind`/`text` in
   `to_dict`, default title); both/neither/empty/over-cap errors;
   no-synthesizer error; add_many validates before synthesizing (fake not
   called when a later item is invalid, playlist unchanged); synthesis
   failure → `PlaylistError`, playlist unchanged; mixed playlist with host
   coords → `engine: "worker"`; worker `play_uri`s items in order including
   the voice URL; shuffle on a mixed playlist plays every item once (voice
   included); shuffled `playlist_status.current_item` matches the item
   actually being played (DD-9); `previous` at index 0 replays index 0
   (DD-10), and back at index 1 goes to index 0; fake reports the hosted voice URI while PLAYING → no takeover;
   all-external track-only playlist still routes `native_queue` with the new
   fields present; `add_many` with `{"url": None, "text": ...}` is a voice
   item and non-`str` fields are rejected; server-level: `playlist_add` with
   `text` only (no `url`) through the in-process FastMCP `Client`; live append — an item appended while the worker
   is on the last item gets played; skip on the last item followed by an
   append plays the appended item; remove-then-append *before the worker reaches the end of order* is still
   detected (not vacuous); skip-on-last racing an add → either the item plays
   or the session is gone, never a live session that drops it;
   removed-index guard exits cleanly.
5. **`playlist_smoke.py`**: `dj` scenario per DD-8, runnable on its own.
6. **Docs**: README (playlist section, agent system-prompt rule 11 + a DJ
   usage rule, tool signatures for `playlist_add`/`add_many`), CLAUDE.md
   (playlists section: item kinds, `PlaylistManager` DI now five params,
   live-append semantics, voice → worker routing), version
   `0.5.0 → 0.6.0` in `mcp_sonos/__init__.py`.

### Cache Freshness Contracts
- **TTS WAV cache** (`{tempdir}/mcp-sonos-audio/tts_<sha1>.wav`): source of
  truth is the (text, voice, length_scale) hash; built at add time; never
  invalidated (content-addressed, so never stale). Accepted risk: if the OS
  cleans tempdir between add and play, that item's `play_uri` fails and the
  worker skips it with a warning (existing skip-on-failure path).
- **Playlist item list** (`Playlist.items`, in-memory): source of truth for
  the worker; rebuild trigger is the worker reaching the end of `order`
  (DD-5: unscheduled items by identity), checked under `self._lock`
  atomically with session deregistration; removals are observed per item.
  Maximum staleness: an appended item waits until everything already
  scheduled has played. Invalidating action: none needed — `add`/`add_many`
  mutate the source directly. After the worker exits, appends are inert until
  the next `playlist_play` (documented).
- **Hosted URL host/port**: `host_ip` is captured once at
  `SonosController.__init__` and the audio host port is bound once at start;
  both are fixed for the process lifetime. Playlists share that lifetime, so
  stored voice URLs cannot outlive their server.
- **Audio host serves at request time**: a TTS file deleted from tempdir
  after add means that item's `play_uri` fails and the worker skips it with a
  warning (existing path) — accepted.

### Checkpoints
- [x] Voice items addable via both tools, unit-tested with a fake synthesizer
- [x] Live append + removed-index guard unit-tested
- [x] Full unit suite green; docs + version bumped
- [x] `playlist_smoke.py dj` passes on real hardware (operator's listening
      check pending)

### Adaptation Criteria

**Divert if**:
- Sonos refuses to `play_uri` the hosted WAV inside a worker sequence (it
  works for `say`; if it fails here, the format/protocol premise is wrong).
- Live append needs a structural rewrite of the worker loop rather than an
  end-of-order extension.

**Acceptable variations**:
- Helper names/placement within `playlists.py`.
- Smoke scenario CLI shape (subcommand vs flag), as long as it runs alone.

### Legs

> **Note:** These are tentative suggestions, not commitments. Legs are planned and created one at a time as the flight progresses. This list will evolve based on discoveries during implementation.

- [x] `voice-items` - Voice item kind (DD-1..DD-4, DD-6, DD-7), live append
      (DD-5), shuffled-status fix (DD-9), previous-at-0 fix (DD-10), unit
      tests, `dj` smoke scenario authored, README/CLAUDE.md, version
      `0.5.0 → 0.6.0`
- [x] `hardware-dj-run` - Run the `dj` smoke scenario on the real household;
      fix anything it surfaces (may spawn a hardening leg, per the M04 F02
      debrief lesson). **Runs unattended overnight** (operator authorized a
      fully autonomous run 2026-10-10): set the target speaker to a low
      volume (≈10) before the run and restore its prior volume after; the
      operator's audible confirmation moves to the morning check-in.

---

## Post-Flight

### Completion Checklist
- [x] All legs completed
- [x] Code merged
- [x] Tests passing
- [x] Documentation updated

### Verification
- `.venv/bin/python -m pytest -q` — green, including
  `tests/test_playlist_voice_items.py`.
- `.venv/bin/python playlist_smoke.py dj` (exact invocation per leg 1) on the
  real household: worker advances track → voice → track, `now_playing` shows
  the hosted WAV during the voice item, live-appended voice item plays,
  operator confirms audibly.
- README agent system prompt describes the DJ pattern.
