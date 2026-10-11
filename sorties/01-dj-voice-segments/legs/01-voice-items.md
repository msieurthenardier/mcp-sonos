# Leg: voice-items

**Status**: completed
**Flight**: [DJ Voice Segments in Playlists](../flight.md)

## Objective
Add a voice item kind to playlists (text synthesized at add time to an
MCP-hosted URL), make the worker engine play items appended during playback,
fix the shuffled-`status()` and previous-at-start defects, and ship unit tests,
a `dj` smoke scenario, docs, and the `0.6.0` version bump. This all happens in
one slice.

## Context
- The flight spec's design decisions are binding. Read DD-1 to DD-10 in
  `../flight.md` before starting; this leg implements all of them except
  the hardware run (DD-8 run happens in leg 2; the scenario is authored here).
- DD-6: shuffle is **allowed** on playlists containing voice items. Add no
  shuffle guard of any kind.
- Routing is untouched (DD-3). Voice URLs come from `AudioHost.url_for`, so
  `any_mcp_hosted` already sends mixed playlists to the worker engine.
- This is the first leg. The flight log has no prior execution notes.
- Baseline: `.venv/bin/python -m pytest -q` → 177 passed (2026-10-10, branch
  `sortie/01-dj-voice-segments`).
- Repo root has four stray empty untracked files (`play`, `play-`, `song-`,
  `voice`). They belong to the operator: do not delete, modify, or stage them.

## Inputs
- `mcp_sonos/playlists.py` — `PlaylistItem` (L56), `PlaybackSession` (L78),
  `PlaylistManager.__init__` (L110), `clear` (L166), `add` (L173),
  `add_many` (L186), `remove` (L205), `_play_via_worker` (L264;
  `order = list(range(len(pl.items)))` at L290), `status` (L495;
  `info["current_item"] = pl.items[sess.current_index].to_dict()` at L515),
  `_worker` (L520; `item = playlist.items[playlist_idx]` L552,
  back handler `session.current_index = max(0, session.current_index - 2)`
  L610, takeover check `current_uri != item.url` L629, `cur is session`
  guard in `finally` L663).
- `mcp_sonos/controller.py` — `self.playlists = PlaylistManager(` (L245);
  `say()` shows the synth→URL pipeline:
  `self.audio.url_for(synthesize(text, self.cache_dir, lang=lang).name)`.
- `mcp_sonos/server.py` — playlist-section comment L309-313 ("subsequent
  tracks will pick them up"), `playlist_add` (L332), `playlist_add_many`
  (L345; up-front url loop L363).
- `playlist_smoke.py` — `main()` (L110) runs the three existing scenarios
  unconditionally against speaker `"Kitchen"`; `build_playlist` uses
  `_smoke_common.select_track_pool`.
- `tests/_fakes.py` (`SoCoFake`), `tests/test_playlists_takeover.py`
  (worker-thread test pattern: `monkeypatch POLL_INTERVAL`,
  `_iteration_event`, bounded waits).

## Outputs
- `mcp_sonos/playlists.py`, `mcp_sonos/controller.py`, `mcp_sonos/server.py`
  modified as described below.
- `tests/test_playlist_voice_items.py` (new). Further new test files are
  allowed if they keep the suite organized.
- `playlist_smoke.py` gains a `dj` scenario selected by argv.
- `README.md`, `CLAUDE.md`, `mcp_sonos/__init__.py` (`0.6.0`) updated.
- Flight log updated with this leg's outcome; leg status `landed`.

## Acceptance Criteria
- [ ] **AC1 Item kind.** `PlaylistItem` has `text: Optional[str] = None`.
      `to_dict()` returns `"kind": "track"` for URL items and
      `"kind": "voice"` plus `"text"` for voice items. Voice items also keep
      `"url"` (the hosted URL) and `"title"`.
- [ ] **AC2 Add paths.** `PlaylistManager.add(name, url=None, *, text=None, title=None)`
      and `add_many(name, items)` accept exactly one of `url`/`text` per
      item. Per DD-1 normalization, a `None`, missing, or
      whitespace-only `url`/`text` is absent. A non-`str` `url`/`text`/
      `title` → `PlaylistError` naming the index (add_many). Both or neither
      → `PlaylistError`. `text` is stored stripped. Text over
      `MAX_VOICE_TEXT_CHARS` (1000) → `PlaylistError` (no truncation).
- [ ] **AC3 Synthesis DI.** `PlaylistManager.__init__` takes
      `synthesize_voice: Optional[Callable[[str], str]] = None`. Adding a
      voice item with it unset → `PlaylistError` explaining voice items are
      unavailable. `add_many` validates every item before synthesizing any.
      An invalid item anywhere → the synthesizer is never called and the
      playlist is unchanged. A synthesizer exception → `PlaylistError`
      (cause chained) and the playlist is unchanged. Synthesis runs outside
      `self._lock`. `SonosController` wires the synthesizer to the same
      pipeline `say` uses.
- [ ] **AC4 Default title (DD-7).** A voice item without a title gets
      `"DJ: " + text[:40]`.
- [ ] **AC5 Routing unchanged.** A mixed playlist (hosted voice URL plus
      external URLs) with real host coordinates plays with
      `engine: "worker"`. An all-external track-only playlist still plays
      with `engine: "native_queue"`. Construct `PlaylistManager` directly
      with `host_ip="192.168.1.50"`, `audio_port=8000` and a synthesizer
      returning `http://192.168.1.50:8000/tts_x.wav`. Do NOT use the
      `stub_controller` fixture: its patched `url_for` returns
      `http://test.invalid/...`, which would route to the native queue.
      Separately, a controller-wiring test shows that `SonosController`'s
      synthesizer goes through `controller_mod.synthesize` and
      `self.audio.url_for`. It must look `synthesize` up as a module global
      at call time so the fixture's patch applies.
- [ ] **AC6 Worker plays voice in order.** The worker `play_uri`s each item's
      URL in playlist order, voice included. When the fake reports the
      hosted voice URI as `PLAYING`, the worker does not treat it as a
      takeover.
- [ ] **AC7 Live append (DD-5, identity-based).** `PlaybackSession` holds
      `order: list[PlaylistItem]` (object refs) and `scheduled_ids: set[int]`,
      built — with the shuffle and every other session field — inside the
      same `self._lock` block that registers the session in
      `_play_via_worker` (closes the register-then-init race). Each worker
      iteration takes `self._lock` once for: extend-or-deregister at end of
      `order` (append unscheduled items by `id()`; deregister with the
      `cur is session` guard if none), skip of items no longer in
      `playlist.items` (identity), and `session.current_item = item`. The
      block calls no helper that takes `self._lock`. `remove`/`clear` gain no
      session bookkeeping. The `finally` fallback pop keeps its guard. Tests
      (deterministic — see guidance §9) show:
      (a) an item appended while the worker is held on the last item is
          played exactly once;
      (b) skip on the last item racing an append (gate inside the fake's
          `stop()`; append while gated; release) plays the appended item
          exactly once;
      (c) with the worker held on item 0 of 3: `remove(2)` then `add(new)`,
          release → play log is item0, item1, new — `new` exactly once,
          removed item never;
      (d) with the worker held on item 0 of 3: `remove(1)` → removed item is
          skipped, item 2 plays, worker exits cleanly (thread dead, session
          deregistered, no exception logged);
      (e) after the worker has exited (thread joined, `_sessions` empty),
          `add` succeeds, `has_active_session` is False, play log unchanged;
      (f) clear-then-add_many while held on item 0 (the `playlist_from_page`
          pattern) → after release, the old items are skipped and each new
          item plays exactly once.
- [ ] **AC8 Shuffled status (DD-9).** `PlaybackSession.current_item` is
      the start item initially and is set by the worker per item.
      `status()["current_item"]` comes from it; `status()` also reports
      `current_playlist_index` (identity search in `pl.items` under the lock,
      `-1` if removed). `to_dict()` keeps `current_index` as the play-order
      position. Test: patch `random.shuffle` to a known non-identity
      permutation (e.g. reversal) so play-order and playlist indices differ;
      `current_item.url` equals the URL the fake is playing.
- [ ] **AC9 Previous (DD-10).** The back handler uses
      `max(-1, current_index - 2)`. Remove the in-handler `if < 0` block and
      keep the top-of-loop `< 0 → 0` clamp. Tests hold the fake on the item
      and set `back_event` (or call `previous_track`): back at play-order
      index 0 replays index 0, and back at index 1 goes to index 0. Assert on
      the next logged `play_uri`.
- [ ] **AC10 Server tools.** `playlist_add` has an optional `url` typed
      `Annotated[Annotated[str, AfterValidator(validate_http_url)] | None, Field(...)] = None`,
      an optional `text`, and `title`. Both tools document voice items, the
      1000-char cap, and that voice items make the playlist use the worker
      engine. `playlist_add_many`'s up-front URL loop skips items whose URL
      is absent. A server-level test calls `playlist_add` with `text` only
      (no `url`) through an in-process FastMCP `Client`, for example a fresh
      `FastMCP` instance plus `register_tools` with a stub controller whose
      `.playlists` is a real `PlaylistManager` with a fake synthesizer. The
      call succeeds and returns a voice item. An invalid `url` scheme still
      fails at the tool boundary (`ToolError` from `client.call_tool`).
      `playlist_add_many` with `{"url": None, "text": "..."}` succeeds as a
      voice item. The server loop must check the raw value before `str()`.
      How: `register_tools` touches `controller` only inside the tool
      closures, so `types.SimpleNamespace(playlists=PlaylistManager(...))` is
      enough. Use a fresh `FastMCP("t")` per test. No async pytest plugin is
      installed, so wrap `async with Client(mcp)` in `asyncio.run(...)` inside
      a sync test.
- [ ] **AC11 Smoke scenario.** `.venv/bin/python playlist_smoke.py dj`
      runs only the new DJ scenario. The no-argument run is unchanged. The
      speaker is set by `SMOKE_SPEAKER` (default `"Kitchen"`) for `dj`, and
      volume by `SMOKE_VOLUME` (optional). If set, the scenario saves the
      speaker's prior volume, applies `SMOKE_VOLUME`, and restores the prior
      volume in a `finally`. The scenario:
      - builds track → voice → track via one `playlist_add_many`;
      - plays the playlist, polls `playlist_status` until
        `current_item.kind == "voice"`, and asserts (via `now_playing`) that
        `PLAYING` with `uri == current_item.url` is observed during that
        item;
      - observes the advance to the next track;
      - appends a voice item with `playlist_add` while the last item plays
        and observes it become `current_item`;
      - stops and deletes the playlist;
      - exits non-zero with a clear message on any failed assertion or
        timeout.
      The scenario must not write snapshot or golden files.
- [ ] **AC12 Docs and version.** README: the tool signatures for
      `playlist_add`/`playlist_add_many`; the playlist two-engine section
      notes that voice items force the worker engine; system-prompt rule 11
      is corrected (live append works on the worker engine while the
      playlist is still playing, a finished playlist needs `playlist_play`
      again, and a native-queue playlist already playing does not pick up
      appends); and a new DJ rule describes the song, song, voice pattern
      with one `playlist_add_many`, playing unshuffled, and keeping
      segments short. The `server.py` L309-313 comment is corrected the
      same way. CLAUDE.md's playlists section covers item kinds, five
      `PlaylistManager` DI params (add `synthesize_voice`), voice →
      worker routing, live-append semantics including the lock rule,
      `current_playlist_index`, and the `playlists.py` module docstring.
      `mcp_sonos/__init__.py` is `__version__ = "0.6.0"`.
- [ ] **AC13 Suite green.** `.venv/bin/python -m pytest -q` passes with
      177 + the new tests, no flakes across 3 consecutive runs.

## Verification Steps
- AC1–AC10: `.venv/bin/python -m pytest -q tests/test_playlist_voice_items.py`
  (plus any other new files). Read the diff for AC3's lock placement and
  AC7's lock-block rule.
- AC11: `.venv/bin/python playlist_smoke.py --help` or a code read
  confirms argv dispatch and the env vars. The real run is leg 2.
- AC12: `grep -n "0.6.0" mcp_sonos/__init__.py`; `.venv/bin/python -m pytest -q tests/test_version.py`;
  read the README/CLAUDE.md diffs.
- AC13: run `for i in 1 2 3; do timeout 300 .venv/bin/python -m pytest -q || break; done`.

## Implementation Guidance

1. **Data model** (`playlists.py`)
   - `PlaylistItem.text` + `kind` property; `to_dict()` per AC1. Note:
     `PlaylistItem` is a dataclass with value equality — use identity
     (`is` / `id()`), never `==`/`in` on lists, for scheduling and the
     removed-item check (two items with the same URL are equal but distinct).
   - `PlaybackSession`: `order: list[PlaylistItem]`, `scheduled_ids: set[int]`,
     `current_item: Optional[PlaylistItem]`; build the session (including the
     shuffle permutation) and register it in one locked block in
     `_play_via_worker`; pass the session (not a separate `order` list) to the
     worker. `to_dict()` unchanged in meaning.
   - `MAX_VOICE_TEXT_CHARS = 1000` module constant.
2. **Normalizer** — one private helper used by both add paths. It returns
   either a ready track item or a pending voice spec (text plus title).
   Error messages carry an `items[i]: ` prefix for `add_many`, matching
   today's idiom.
3. **add / add_many** — normalize all items, then synthesize the pending
   voice specs outside the lock (wrapping exceptions), then append under
   `self._lock`. `add` keeps calling `_get_playlist` first so an unknown
   playlist fails before any synthesis.
4. **remove / clear** — no change. Identity scheduling needs no session
   bookkeeping.
5. **Worker** (`_worker`) — restructure the top of the outer loop per the
   flight spec's DD-5: one locked block for extend-or-deregister, removed-item
   skip (identity), and `current_item`; title default comes from the item
   (voice items already carry one per AC4); keep the `finally` fallback pop
   with its `cur is session` guard; back handler per AC9.
6. **status()** — `current_item` from `sess.current_item`;
   `current_playlist_index` by identity search, under the existing lock.
7. **Controller** — pass
   `synthesize_voice=lambda text: self.audio.url_for(synthesize(text, self.cache_dir).name)`
   or an equivalent small private method to `PlaylistManager(...)`.
8. **Server** — AC10. Keep business logic out of `server.py`.
9. **Tests** — required fake support:
   - Add `play_uri_log: list[tuple[str, str]]` to `SoCoFake` (record every
     `play_uri(uri, title)`); keep the rest of its behavior.
   - Write a **test-local gated subclass** in the new test file: `play_uri`
     logs and sets a per-call event; `get_current_transport_info` reports
     `PLAYING` while the current URI is "held", `STOPPED` once released;
     `stop()` can optionally block on a gate event (for AC7(b)) after
     signalling it was entered. Tests hold/release items instead of flipping
     `_transport` from the test thread.
   - Wait on the fake's per-call events / `play_uri_log` length — not on
     `manager._iteration_event` alone (it is set and never cleared).
   - Never hold `manager._lock` from the test thread (add/remove would
     deadlock). Only bounded waits (`Event.wait(2.0)`, `thread.join(2.0)`)
     with asserted results. Patch `POLL_INTERVAL` small. Every test that
     starts a worker stops it in a `finally` (`manager.stop(...)` or
     `delete`) so no thread outlives the test.
10. **Smoke** — AC11. Argv dispatch must not run the three legacy
    scenarios for `dj`; the volume restore sits in a `finally` that also
    covers assertion failures and `sys.exit`. Reuse `_smoke_common.select_track_pool`. Keep the
    scenario short: short tracks, and a `playlist_next` past the long
    parts is fine as long as the voice item and the appended voice item
    are each observed playing.
11. **Docs and version** — AC12.

## Edge Cases
- **Duplicate text**: the TTS cache returns the same file, so two voice
  items share a URL. That is fine. Takeover detection compares URIs, so
  two adjacent identical voice items still play (the URI matches).
- **Voice item at index 0 / last**: no special casing.
- **`playlist_from_page`** during playback: AC7(f) covers this.
- **Identical voice text twice**: these are two distinct `PlaylistItem`
  objects with an equal URL. Identity scheduling plays both. Never use
  `==`/`in` on item lists, because the dataclass compares by value.
- **Synthesizer returns a non-hosted URL** (tests): routing then follows the
  URL as usual. This is not a production concern.
- **Worker exits while `add` waits for the lock**: AC7(e) covers this.

## Design Review Addendum (cycle 2, binding)
These points override any earlier wording in this leg that conflicts with them.

1. **Locked-block loop order.** Each worker iteration runs one `with self._lock:`
   block containing a `while True` loop:
   1. If `current_index >= len(order)`, append unscheduled items by `id()`.
      If none were added, deregister (guarded by `cur is session`) and exit
      the worker.
   2. If `order[current_index]` is not present (check
      `any(x is item for x in playlist.items)`, never `in`),
      `current_index += 1` and `continue`.
   3. Otherwise set `session.current_item` and `break`.

   A removed tail therefore re-triggers extend-or-exit and never raises
   `IndexError`. This is the AC7(c)/(f) path.
2. **Previous onto a removed item (DD-10).** The back handler takes
   `self._lock` briefly (not nested in anything else) and scans backward
   from `current_index - 1` for the nearest present item. It sets
   `current_index` so that after the outer `+1` it lands on that item. If
   none exists, it replays the current item; at index 0 it replays index 0.
   Add a test: hold on item 2 with item 1 removed, fire back, and assert the
   next `play_uri` is item 0.
3. **Title fallback.** A track item without a title plays as
   `f"{playlist_name} #{current_index + 1}"` (play-order position), computed
   in the block. Voice items always carry their DJ title.
4. **`_play_via_worker` response.** Take `first_item` (from
   `session.current_item`) and `total_items` inside the registering locked
   block, not by reading `pl.items` after `t.start()`.
5. **`status()` after delete.** If the playlist was deleted
   (`pl is None`), `current_item` still comes from the session, and
   `current_playlist_index` is `-1`. State this in AC8.
6. **AC7(d) "no exception logged"**: use `caplog` at ERROR level (the
   worker logs `log.exception("playlist worker crashed")`). Also assert
   that the thread has died.
7. **Fake determinism.**
   - Each `play_uri` call logs, sets that call's event, and resets
     `held=True`.
   - A release makes `get_current_transport_info` return `STOPPED` and
     keep returning it until the next `play_uri`, so the worker sees its
     two STOPPED reads.
   - A gated `stop()` must not block once released. Every `finally`
     releases all gates before calling `manager.stop(...)`.
   - (b) asserts exactly-once only. It need not claim to force the race.
   - (d) releases items 0 and 2.
   - AC8 patches `mcp_sonos.playlists.random.shuffle` with an in-place
     function such as `lambda x: x.reverse()`, and asserts after the second
     item is playing.
   - AC9 advances to index 1 by releasing item 0, then fires back.
8. **Citation Audit.** The Inputs line numbers describe the code *before*
   this leg. They will drift once it is implemented, and that is expected.

## Files Affected
- `mcp_sonos/playlists.py` — item kind, normalizer, synthesis DI, live
  append, DD-9, DD-10, docstring.
- `mcp_sonos/controller.py` — synthesizer wiring.
- `mcp_sonos/server.py` — `playlist_add`/`playlist_add_many` schema and
  docs, playlist-section comment.
- `tests/test_playlist_voice_items.py` — new.
- `tests/_fakes.py` — `SoCoFake.play_uri_log` (required).
- `playlist_smoke.py` — `dj` scenario and argv dispatch.
- `README.md`, `CLAUDE.md`, `mcp_sonos/__init__.py`.

## Citation Audit
All line numbers were checked against the working tree on
`sortie/01-dj-voice-segments` at 2026-10-10 (grep of the quoted snippets).
None have drifted.

---

## Post-Completion
Completion steps (status transitions, flight-log update, checking off in the
parent flight, and commit) are Flight Control protocol, driven by the
execution workflow. They are not repeated here.
