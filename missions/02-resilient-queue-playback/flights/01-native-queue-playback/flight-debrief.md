# Flight Debrief: Native Queue Playback Path

**Date**: 2026-06-01
**Flight**: [Native Queue Playback Path](flight.md)
**Status**: landed
**Duration**: single session (2026-06-01)
**Legs Completed**: 5 (Legs 1–4 + Leg 6 version-reporting; Leg 5 optional — not run)

## Outcome Assessment

### Objectives Achieved
`playlist_play` now plays all-external playlists through Sonos's **native queue**,
so playback advances speaker-side and **survives an MCP reap**. Verified live: the
shipped code path loaded a queue, the MCP process was killed, and the Kitchen/Patio
group kept playing and advanced track 1 → track 2 with no MCP involvement. Playlists
containing any MCP-hosted URL fall back to the unchanged worker engine.

### Mission Criteria Advanced
- **Q1** (survive reap) — ✅ proven on hardware via the shipped code path
- **Q2** (bulk enqueue with titles) — ✅ mechanism (DIDL via `add_multiple_to_queue`);
  filename/title floor confirmed; ID3-vs-DIDL now-playing-title nuance carried forward
- **Q3** (native ordering) — ✅ `play_mode` (`SHUFFLE_NOREPEAT`/`NORMAL`), no in-process permutation on the queue path
- **Q5** (worker fallback) — ✅ any MCP-hosted URL routes to the unchanged worker engine
- **Q6-partial** (worker eviction) — ✅ queue-path play evicts a live worker session first
- Deferred: Q4 + Q6-takeover → Flight 2; Q7 docs → Flight 3

All flight checkpoints met. Test suite: **38 hardware-free tests, 100% pass, ~0.28s.**

## What Went Well
- **Hard-gate-first paid for itself.** Leg 1 (hardware spike) surfaced that
  `add_multiple_to_queue` rejects bare URL strings (`AttributeError`) and requires
  DIDL objects — not obvious from SoCo docs and would have been a runtime crash if
  discovered in Leg 3. The DIDL recipe, `parent_id != "-1"` rule, title-stickiness
  nuance, and "avoid single `add_to_queue`" all came from one cheap gate leg.
- **Design reviews caught real issues before code.** The Leg 3 review caught three
  that would have caused rework: the retry helper is hardcoded to `play_uri` (→ sibling
  helper DD-A), `SHUFFLE` loops forever (→ `SHUFFLE_NOREPEAT` DD-B), and only
  `next`/`previous` raise on no-session (vs. `stop`/`status` already graceful).
- **Two-engine seam is clean.** Single routing gate in `play()`, two co-equal private
  methods (`_play_via_worker`/`_play_via_queue`), identical return shape + an `engine`
  discriminator. Worker engine behavior provably unchanged (extracted verbatim).
- **Eviction race genuinely closed and tested.** `test_queue_play_evicts_worker_before_queue_load`
  patches `clear_queue` to assert the worker thread is dead at call time — a real
  timing-invariant assertion, not a call-count check.
- **First real regression net.** This is the first flight in the project where
  `pytest` returns results (38 tests). It seeds the baseline for all future debriefs.
- **The debrief itself caught a real bug.** Questioning version reporting during the
  debrief surfaced that the MCP advertised FastMCP's framework version (`3.3.1`), not
  its own — fixed same-session in **Leg 6** (single source of truth in
  `__init__.__version__` → hatchling dynamic → `FastMCP(version=…)`, guard test, bumped
  to `0.2.0`), with the convention documented in CLAUDE.md.

## What Could Be Improved

### Process
- **Flight-log bookkeeping drifted.** The log records "16 new (Leg 3)" / "36 passed
  (Leg 4)", but the post-fix reality is 18 / 38 (two URL-encoding tests added in the
  review-fix pass after the snapshot). Record counts at commit time, not at a mid-leg
  `pytest` run.

### Technical
- **`stop()`/`status()` actively misrepresent live state for queue-backed playback.**
  With no `_sessions` entry, both return `{"running": False}` while the speaker is
  audibly playing from the native queue — and `stop()` does not call `coord.stop()`,
  so it's a silent no-op. This is the most awkward consequence of the cross-flight
  seam: the tool contract contradicts reality between now and Flight 2. Makes Flight 2
  high-priority, not optional polish.
- **Stale-coord cache-flush asymmetry.** `_play_from_queue_with_stale_coord_retry`
  (in `playlists.py`) re-resolves via the injected callback but does NOT flush the
  speaker cache, whereas `_play_uri_with_stale_coord_retry` (in `controller.py`) sets
  `_speakers_ts = 0.0` first. A retry within the 30s TTL reuses the stale coordinator —
  latent bug. Low-risk (symptom never observed) but the two helpers are subtly divergent.
- **Blank `now_playing.title` during queue playback.** Sonos firmware prefers embedded
  ID3 tags over DIDL metadata for the transport now-playing title; tracks without an
  ID3 title show blank (artist/album DID populate from ID3). `playlist_status` (reads
  the playlist item) still shows the title; `now_playing` (reads live transport) does not.
- **`engine` discriminator is inconsistent** — present in play results and the graceful
  `next`/`previous` responses, absent from `stop`/`status`.
- **Dead code residue.** `_play_from_queue_with_stale_coord_retry`'s return value is
  unused by its caller; `_session_for` is defined but uncalled (scaffolded for Flight 2).
- **Coverage gaps.** No tests for: `status()` no-session path; `play_mode`-set-before-
  `play_from_queue` ordering (a real behavioral invariant); the `SoCoSlaveException`
  retry branch (zero coverage).

### Test Metrics (seed baseline)
First flight in the project to run `pytest`: **41 passed, 0 failed, 0 skipped, ~0.9s
wall-clock**, no flakes (38 at the queue-path landing + 3 from the post-debrief Leg 6
version work). Modules: `test_queue_path.py` (18), `test_urls.py` (13),
`test_tts_verify.py` (4), `test_say_coordinator.py` (2), `test_playlists_takeover.py` (1).
The three Mission-01 debriefs all recorded "0 unit tests / pytest unavailable"; the
M1F4 test-scaffolding obligation effectively landed here. These numbers seed future
comparisons. (Env note: the suite requires the venv active — `pytest` from a bare
`python3` fails with `ModuleNotFoundError: soco`.)

### Documentation
- CLAUDE.md does not yet describe the two-engine architecture, the routing rule, the
  `PlaylistManager(host_ip, audio_port)` constructor params, or the `engine` contract.
- `QUEUE_PARENT_ID = "A:TRACKS"` has a code comment but no audit-trail pointer to the
  Leg 1 finding that `"-1"` loses titles.
- Known limitations to document: `stop`/`status` session-only until Flight 2; Sonos app
  shows empty queue for DIDL-injected items (accepted); title-stickiness/ID3 precedence.
- All docs are mission Q7 → **Flight 3**; intentionally not done here.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| No host/port configured → route to worker engine (not queue) | Without audio-host coords, can't classify; sending TTS to the queue would be wrong. Preserves pre-Leg-3 behavior. | Yes — conservative-fallback-on-missing-config is a sound default |
| `PlaylistManager` absorbed `host_ip`/`audio_port` constructor params | Higher cohesion — the manager owns the routing decision; controller change stays 3 lines | Yes — matches the existing `resolve_coordinator` DI pattern |
| Retry helper placed in `playlists.py` (sibling, not refactor of controller's) | Controller's `play_uri` helper is pinned by `say()` tests; refactoring risked them | Acceptable; watch for drift if a third retry site appears |
| Leg 5 (guided HAT) not run | Operator satisfied after the Q1 reap HAT | n/a |

## Key Learnings
- A **hard-gate hardware spike before any code** is the right pattern when the core
  mechanism rests on undocumented third-party/firmware behavior. One leg de-risked the
  whole flight and produced a concrete recipe the implementer followed verbatim.
- **Cross-flight seams need explicit contract honesty.** Deferring the control surface
  to Flight 2 is fine, but leaving `stop`/`status` returning `running: False` while music
  plays means the contract lies in the interim. Future seam-splitting should at minimum
  make the deferred tools *say* "not controllable yet (engine: native_queue)" rather than
  assert a false idle state.
- **Witnessed/independent review works.** Architect (flight) + Developer (per-leg) +
  independent Reviewer (final) each caught issues their predecessor didn't.

## Recommendations
1. **Treat Flight 2 as high-priority.** Make `stop` actually stop the native queue,
   `status`/`next`/`previous` read/drive live coordinator state, and standardize the
   `engine` key across all `playlist_*` tools. The interim half-state is the biggest
   user-facing wart.
2. **Close the stale-coord cache-flush asymmetry** in Flight 2 — inject an
   `invalidate_speakers_cache` callback into `PlaylistManager` (alongside
   `resolve_coordinator`) so the queue retry flushes the cache like the controller's does.
   Add a test that raises `SoCoSlaveException` from `play_from_queue` and asserts retry.
3. **Flight 2 status reporting should read `artist`/`album` from `now_playing`, not
   `title`** (ID3-precedence makes `title` unreliable for queued items). Document the
   limitation.
4. **Add the two uncovered tests now or in Flight 2**: `play_mode`-before-`play_from_queue`
   ordering invariant, and `status()` no-session behavior.
5. **Clean up dead code** (`_play_from_queue_with_stale_coord_retry` return; unused
   `_session_for`) when Flight 2 touches these paths.

## Action Items
- [ ] Flight 2: `playlist_stop` calls `coord.stop()` on no-session queue playback (no silent no-op)
- [ ] Flight 2: `playlist_status`/`next`/`previous` operate on live coordinator state; add `engine` key everywhere
- [ ] Flight 2: inject `invalidate_speakers_cache` into `PlaylistManager`; flush cache in queue retry; test the `SoCoSlaveException` branch
- [ ] Flight 2: status uses `artist`/`album` (not `title`) for queued tracks
- [ ] Flight 2/maintenance: add tests for `play_mode` ordering + `status()` no-session; remove dead code
- [ ] Flight 3 (docs): CLAUDE.md two-engine architecture, `PlaylistManager` constructor params, `engine` contract, `QUEUE_PARENT_ID` audit-trail pointer, known limitations (stop/status interim, empty app queue, ID3 title-stickiness)
- [ ] Bookkeeping: record test counts at commit time in flight logs
