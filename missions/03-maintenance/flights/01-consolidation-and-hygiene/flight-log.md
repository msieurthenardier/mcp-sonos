# Flight Log: Consolidation & Hygiene

**Flight**: [Consolidation & Hygiene](flight.md)

## Summary
In-flight (2026-06-02). 12-leg maintenance flight executed via `/agentic-workflow`.

---

## Leg Progress

### Leg 02 — unify-stale-coord-retry
- **Status**: landed
- **Changes Made**:
  - Created `mcp_sonos/_retry.py` with a single `with_stale_coord_retry(coord, action, invalidate, resolve)` helper. Returns the coordinator that succeeded (preserving the controller path's return contract). Cycle-free: neither controller nor playlists previously imported it.
  - `controller.py`: removed `_play_uri_with_stale_coord_retry`; call site in `_say`/`_say_one` now calls `with_stale_coord_retry` with `invalidate=lambda: setattr(self, "_speakers_ts", 0.0)` (preserves the `self._speakers_ts = 0.0` cache-flush) and `resolve=lambda: self._resolve_coordinator(target)[1]`.
  - `playlists.py`: removed `_play_from_queue_with_stale_coord_retry`; call site in `_play_via_queue` now calls `with_stale_coord_retry` with `invalidate=self._invalidate_speakers_cache` and `resolve=lambda: self._resolve_coordinator(speaker.player_name)[1]`. Dead return value (I-4) eliminated.
- **Notes**: Both call sites verified: controller path invalidates via `_speakers_ts = 0.0`; playlists path invalidates via injected callback. 63 tests, 2.52s.

### Leg 08 — parametrize-skip-guard-tests
- **Status**: landed
- **Changes Made**:
  - `tests/test_queue_resume.py`: Replaced three standalone skip-guard tests (`test_no_queue_skip_no_play_from_queue`, `test_not_playing_skip_no_play_from_queue`, `test_playlist_position_zero_skip_no_play_from_queue`) with one `@pytest.mark.parametrize` test `test_skip_guard_no_play_from_queue` over `(queue, transport_state, playlist_position)` with three `pytest.param(…, id=…)` cases: `empty-queue`, `not-playing`, `position-zero`. Each case uses `_make_speaker_playing_queue` with a single-field override. Assertion is `play_from_queue_last_index is None` (identical to the three originals).
- **Notes**: Three standalone tests replaced by one parametrized test with three cases — net test count unchanged at 63 (3 removed + 3 parametrized = same count). Failure names now identify the guard term. ~25 lines of duplicated inline `_track` dicts removed. 63 tests, 1.06s.

### Leg 07 — parametrize-resume-tests
- **Status**: landed
- **Changes Made**: None — merge set determined to be 0 after full enumeration.
- **Notes**: Enumerated all 14 tests in `test_queue_resume.py`. Every test asserts at least one distinct behavioral property beyond the shared "resumes at position-1, seeks to snapshot" observable: `test_say_resumes_queue_after_announcement` pins `play_from_queue`-before-`play_mode` ordering; `test_say_resumes_with_non_default_play_mode` pins non-default play_mode; `test_play_url_resumes_queue_and_blocks` pins blocking + `PLAY_URL_RESUME_TIMEOUT_SECONDS` timeout; `test_play_url_returns_post_resume_state` pins return-dict shape; `test_play_file_inherits_resume` pins delegation; remaining 9 are guard/failure/seek tests from the must-NOT-fold list. The shared `play_from_queue_last_index == position-1` + `seek_last == snapshot` assertions appear in multiple tests, but since each test's distinct pin means the test must remain standalone, there is nothing to collapse without losing a guard. Applied the spec's asymmetric rule ("over-keeping costs lines; over-collapsing loses a regression guard") and kept all 14. 14 resume tests, 63 total, 1.05s.

### Leg 06 — worker-session-fixture
- **Status**: landed
- **Changes Made**:
  - `tests/_builders.py`: Added `worker_session(mgr, speaker, playlist_name)` context manager. Patches `playlists_mod.POLL_INTERVAL` to 0.01, creates and plays an MCP-hosted playlist (worker engine), yields the `PlaybackSession` object, and in `finally:` restores `POLL_INTERVAL` and calls `mgr.stop` (swallowing errors). This closes the missing-cleanup gap that `test_worker_session_stop_returns_engine_worker` had.
  - `tests/test_queue_path.py`: Added `worker_session` to import from `_builders`. Migrated four tests (`test_queue_play_evicts_worker_before_queue_load`, `test_worker_session_path_unchanged_for_next`, `test_worker_session_path_unchanged_for_previous`, `test_worker_session_stop_returns_engine_worker`) to use `with worker_session(mgr, speaker, playlist_name=...) as sess:`. `POLL_INTERVAL` save/restore/`mgr.stop` boilerplate no longer appears in any test body.
- **Notes**: Eviction test (`test_queue_play_evicts_worker_before_queue_load`) accesses `sess.thread` inside the `with` body; the `clear_queue` patch happens after yield as required. 63 tests, 1.09s.

### Leg 05 — shared-test-builder
- **Status**: landed
- **Changes Made**:
  - Created `tests/_builders.py` with: `_HOST_IP`, `_AUDIO_PORT`, `_MCP_URL` constants (migrated from `test_queue_path.py`); and `make_speaker_playing_queue(...)` builder (generalized from `test_queue_resume.py`'s `_make_speaker_playing_queue`) accepting overrides for `queue`, `transport_state`, `playlist_position`, `uri`, `title`, `artist`, `album`, `position`, `duration`.
  - `tests/test_queue_resume.py`: Added import of `make_speaker_playing_queue`; replaced local `_make_speaker_playing_queue` definition with alias `_make_speaker_playing_queue = make_speaker_playing_queue`.
  - `tests/test_queue_path.py`: Added import of `_HOST_IP`, `_AUDIO_PORT`, `_MCP_URL`, `make_speaker_playing_queue` from `_builders`; removed local constant definitions; replaced the three inlined `_track`/`_transport` dicts at `test_next_track_no_session_invokes_coord_next`, `test_previous_track_no_session_invokes_coord_previous`, `test_status_no_session_returns_live_state` with builder calls using field overrides.
- **Notes**: No assertion changes. Constants defined once; builder defined once. 63 tests, 1.05s.

### Leg 04 — say-all-sleep-seam
- **Status**: landed
- **Changes Made**:
  - `controller.py`: Added `self._sleep = time.sleep` injectable attribute in `__init__` (after `PlaylistManager` construction). Both `time.sleep` calls in `_say_all` (0.5s dissolve-settle and 1.0s partymode-settle) now invoke `self._sleep(...)` instead of `time.sleep(...)`. Production default is unchanged.
  - `tests/test_queue_resume.py::test_say_all_no_resume`: Added `stub_controller._sleep = lambda *_: None` after speaker wiring so neither settle costs real time.
- **Notes**: Suite wall-clock dropped from 2.54s → 1.00s (the 1.0s outlier is gone; `test_say_all_no_resume` no longer appears in `--durations=5`). 63 tests, 1.00s.

### Leg 03 — extract-live-track-dict
- **Status**: landed
- **Changes Made**:
  - Added `PlaylistManager._live_track_dict(track, speaker_name)` static method in `playlists.py`. Builds the `{engine, speaker, title, artist, album, position, duration, uri, playlist_position}` dict with `""` empty-string defaults. Docstring documents deliberate divergence from `controller._track_state` (which uses `None` defaults and a `state` key but no `engine`/`speaker`/`playlist_position`).
  - `next_track` and `previous_track` no-session paths now call `self._live_track_dict(track, speaker.player_name)` — dict construction no longer duplicated.
  - `status` no-session path: early-return guard (`if state in ("STOPPED", "") or not track.get("uri")`) stays in `status` before the helper call; the full-state return is `{**self._live_track_dict(track, speaker.player_name), "state": state}`.
- **Notes**: `get_current_track_info()` is still called at each site (the advance + read pattern stays per-method); only the dict construction is deduplicated. `controller._track_state` left read-only with a divergence comment in the helper. 63 tests, 2.52s.

---

## Flight Director Notes

**Branch**: `flight/01-consolidation-and-hygiene` off `main` (scaffold + 2026-06-02 report committed to main as `eaf262f`).
**Crew**: `leg-execution.md` loaded and validated (Developer/Reviewer, Sonnet). Mission flipped `planning`→`active`; flight `ready`→`in-flight`.

**Orchestration decisions for this run (logged per skill Decision Log):**
- *Consolidated design review.* The 12 legs were authored in detail during the routine-maintenance scaffold and grounded against live code by the inspection agents. Rather than 12 separate design-review spawns, one Developer design-reviews all 12 leg specs against the codebase in a single pass — chiefly to correct the line-reference drift flagged in several specs (e.g. I-5's `playlists.py` read sites). Per-leg re-review only if a high-severity issue surfaces for a specific leg.
- *Grouped implementation.* This skill commits once at the end (no per-leg commits), so implementation is grouped by area into a few Developer agents — source-dedup (legs 02–03), test-infra+consolidation (legs 04–08), smoke (leg 09), docs+hygiene (legs 01, 10–12) — sequenced source→tests→smoke→docs so test legs run against the refactored source. Each Developer still updates the flight log + per-leg statuses, preserving atomic tracking.
- *Single flight review + commit* at the end (Phase 2d) over all uncommitted changes.

**Design review (consolidated, 1 Developer, Sonnet):** all 12 legs approved (6 "approve", 6 "approve with changes"). Confirmed the green 63-test / ~3.0s baseline. Corrections incorporated into specs as "Design-review note" callouts on legs 02, 03, 05, 07, 11 — chiefly: corrected line refs (locate-by-symbol); leg 02 behavior-preservation (verify the controller's `invalidate_speakers_cache` zeros `_speakers_ts` before collapsing); leg 03 the two live-track readers are structurally incompatible (document divergence, don't force a shared base) and `status`'s early-return guard stays outside the helper; leg 05 the `_HOST_IP`/`_AUDIO_PORT`/`_MCP_URL` constants live only in `test_queue_path.py`; leg 07 must-NOT-fold list (the ordering/timeout/delegation tests) and the real merge set is 2-3, not 4. No re-review needed — changes were incorporations of the reviewer's own corrections.

---

## Decisions

---

## Deviations

---

## Anomalies

---

## Session Notes
