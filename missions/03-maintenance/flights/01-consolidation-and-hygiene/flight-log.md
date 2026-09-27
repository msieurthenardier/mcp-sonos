# Flight Log: Consolidation & Hygiene

**Flight**: [Consolidation & Hygiene](flight.md)

## Summary
Landed 2026-09-26. 12-leg maintenance flight executed via `/agentic-workflow`: legs 02–08 shipped in `881d152` (PR #8); legs 01, 09–12 completed on resume under plugin 1.1.0. Suite: 78 passed.

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

### Leg 01 — gitignore-env
- **Status**: landed
- **Changes Made**:
  - `.gitignore`: added a `.env` entry (with a comment noting `.env.example` is the tracked template) directly below the existing `.mcp.json` local-config entry.
- **Notes**: `git check-ignore .env` → prints `.env`; `git check-ignore .env.example` → empty (template stays tracked); no local `.env` exists and `git log --all -- .env` is empty (never committed, nothing to scrub). `git status --short` shows only the intended edits, no removals.

### Leg 10 — reword-tool-count-comment
- **Status**: landed
- **Changes Made**:
  - `CLAUDE.md`: reworded the `AUDIO_MEDIA_ROOT` eager-parse bullet in "When extending" (now at line ~242, drifted from the leg's original `:240` citation) from "the other 32 tools keep working" to "the remaining tools keep working" — drops the bare count that read as drift against the file's own "35 tools" assertion.
- **Notes**: Per the leg's citation audit, the actual tool count had moved from 32→35 since authoring; fix intent unchanged (drop the number, don't correct it to a new one). `grep -n "31" CLAUDE.md` → no hits. `grep -rn "35" CLAUDE.md README.md mcp_sonos/server.py` → the three "35 tools" assertions remain (`CLAUDE.md:8`, `server.py:49`, `README.md:14`/`449`). `grep -c "@mcp.tool" mcp_sonos/server.py` → 35, confirming the assertions are accurate.

### Leg 11 — merge-queue-parent-id-comment
- **Status**: landed
- **Changes Made**:
  - `mcp_sonos/playlists.py`: merged the duplicated `QUEUE_PARENT_ID` comment block (previously stating the `parent_id != "-1"` firmware invariant twice — once as "Must NOT be -1..." and again as a "NOTE: Flight 1 hardware finding...") into a single paragraph. Retained the rule (`parent_id` must not be `"-1"`; `"A:TRACKS"` is the conventional container) and the Flight 1 hardware-finding provenance in one pass; did not add a `CLAUDE.md` line reference (per the leg's design-review correction).
- **Notes**: `grep -n "A:TRACKS" mcp_sonos/playlists.py` shows the declaration and its usage unchanged. Comment-only change; no code touched.

### Leg 12 — codify-dir-listing-guard
- **Status**: landed
- **Changes Made**:
  - `CLAUDE.md`: added a new bullet to "When extending" (alongside the cross-cutting-validation and eager-parse-env-var idioms) documenting that `audio_host.py`'s `list_directory` → 404 override is deliberate — the host binds `0.0.0.0` unauthenticated on the LAN (firewall-scoped, accepted threat model) and listing would expose the staged-file directory — and must be preserved on any refactor of the handler.
- **Notes**: Confirmed `audio_host.py:78-80` still has the guard (`send_error(404)`) before documenting it. `grep -n "list_directory" CLAUDE.md` → the new bullet is present. Bullet matches the bold-lead-in / example / rationale format of the surrounding codified idioms.

### Leg 09 — smoke-fallback-url
- **Status**: landed
- **Changes Made**:
  - Added `_smoke_common.py` (repo root, sibling to the smoke scripts — not part of the `mcp_sonos` package, not collected by pytest) with `EXTERNAL_TRACKS_PRIMARY` (SoundHelix, unchanged), a new `EXTERNAL_TRACKS_FALLBACK` (a different host), `TRACK_POOLS`, a stdlib-only `_reachable(url, timeout)` probe (HEAD, retrying with a 1-byte ranged GET if the host rejects HEAD with 405/501), and `select_track_pool(pools, timeout)` which probes each pool's first URL in order and returns the first reachable one (falling through to the last pool, unprobed, if every candidate fails, so a total outage surfaces as a clear enqueue failure rather than an empty playlist).
  - `queue_smoke.py`: removed the hardcoded `EXTERNAL_TRACKS` module constant; `main()` now calls `select_track_pool()` right after the hardware-reachability check and prints which host was selected. Docstring updated to describe the primary/fallback pool and the probe, with the single-host-outage-only caveat and the probe-runs-from-this-machine caveat.
  - `reap_smoke.py`: removed the hardcoded `EXTERNAL_TRACKS` module constant; the pool selection call was placed inside `phase_load()` only (not at module import time), so `--control` never pays the probe's network cost and never depends on re-probing landing on the same pool `--load` picked — `--control` doesn't touch the track list at all, it only drives the already-live queue via `playlist_status`/`playlist_next`/`playlist_stop`. Docstring updated with the same primary/fallback + caveats language as `queue_smoke.py`.
- **Notes**:
  - Chosen fallback host: **filesamples.com** (`https://filesamples.com/samples/audio/mp3/sample{1,2,3}.mp3`) — a different host from SoundHelix. Verified 2026-09-26 from this machine: `curl -sI --max-time 5` on all three URLs returned `200`/`audio/mpeg`, and a ranged GET (`-r 0-15`) on each confirmed a real MP3 body (`ID3...` magic bytes), not an HTML placeholder. Several other public-sample candidates were tried and rejected first (hyperionics.com 404, sample-videos.com/jplayer.org serve HTML "not found" pages despite 200 status, noiseaddicts.com only had one guessable working path — not enough for a 3-track pool). Note the existing primary (SoundHelix) is also HTTPS-only, so choosing an HTTPS-only fallback is consistent with existing precedent, not a new regression against CLAUDE.md's HTTP-preferred guidance.
  - Fallback-path verification (no hardware; per the leg's guidance to use a python one-liner, not a code hack left in the tree): ran `_smoke_common.select_track_pool()` unmodified against the real primary (selected SoundHelix, confirming the live host is up), then called it again with an unreachable dead-host pool substituted as the first argument — it correctly selected the filesamples fallback pool — and a third call with two dead pools confirmed the total-outage fallthrough returns the last pool rather than raising. No temporary code was left in `_smoke_common.py`, `queue_smoke.py`, or `reap_smoke.py`; `git status --short` shows only the intended new/modified files.
  - `python -m py_compile queue_smoke.py reap_smoke.py _smoke_common.py` → clean.
  - `pytest --collect-only -q` → 78 tests collected, `_smoke_common.py` not among them (confirms `testpaths=["tests"]` and `packages=["mcp_sonos"]` in `pyproject.toml` don't need changes for a new root-level helper).
  - `timeout 300 .venv/bin/python -m pytest -q` → 78 passed in 1.40s (suite has grown from the flight-start baseline of 63/72 to 78 via unrelated tool additions since flight start; unaffected by this leg).
  - `git status --short` → no MP3 or other binary added; only `_smoke_common.py` (new) and `queue_smoke.py`/`reap_smoke.py` (modified) from this leg's work. Did not touch `.gitignore`, `CLAUDE.md`, or `mcp_sonos/playlists.py` (owned by the concurrent Developer on legs 01/10/11/12).
  - README has no description of the smoke scripts' track sourcing, so no README update was needed.

---

## Flight Director Notes

**Branch**: `flight/01-consolidation-and-hygiene` off `main` (scaffold + 2026-06-02 report committed to main as `eaf262f`).
**Crew**: `leg-execution.md` loaded and validated (Developer/Reviewer, Sonnet). Mission flipped `planning`→`active`; flight `ready`→`in-flight`.

**Orchestration decisions for this run (logged per skill Decision Log):**
- *Consolidated design review.* The 12 legs were authored in detail during the routine-maintenance scaffold and grounded against live code by the inspection agents. Rather than 12 separate design-review spawns, one Developer design-reviews all 12 leg specs against the codebase in a single pass — chiefly to correct the line-reference drift flagged in several specs (e.g. I-5's `playlists.py` read sites). Per-leg re-review only if a high-severity issue surfaces for a specific leg.
- *Grouped implementation.* This skill commits once at the end (no per-leg commits), so implementation is grouped by area into a few Developer agents — source-dedup (legs 02–03), test-infra+consolidation (legs 04–08), smoke (leg 09), docs+hygiene (legs 01, 10–12) — sequenced source→tests→smoke→docs so test legs run against the refactored source. Each Developer still updates the flight log + per-leg statuses, preserving atomic tracking.
- *Single flight review + commit* at the end (Phase 2d) over all uncommitted changes.

**Design review (consolidated, 1 Developer, Sonnet):** all 12 legs approved (6 "approve", 6 "approve with changes"). Confirmed the green 63-test / ~3.0s baseline. Corrections incorporated into specs as "Design-review note" callouts on legs 02, 03, 05, 07, 11 — chiefly: corrected line refs (locate-by-symbol); leg 02 behavior-preservation (verify the controller's `invalidate_speakers_cache` zeros `_speakers_ts` before collapsing); leg 03 the two live-track readers are structurally incompatible (document divergence, don't force a shared base) and `status`'s early-return guard stays outside the helper; leg 05 the `_HOST_IP`/`_AUDIO_PORT`/`_MCP_URL` constants live only in `test_queue_path.py`; leg 07 must-NOT-fold list (the ordering/timeout/delegation tests) and the real merge set is 2-3, not 4. No re-review needed — changes were incorporations of the reviewer's own corrections.

**Resume — 2026-09-26 (plugin 1.1.0).**
- *State reconciliation.* Legs 02–08 landed and shipped to `main` in `881d152` (merged via PR #8) alongside out-of-flight work (`reboot` tool, soco bump); the original flight branch was deleted on merge. That commit's message claims "legs 02-11", but leg 11's code fix was never made — only its spec was edited. Legs 01, 09, 10, 11, 12 remain `ready` with no log entries. Suite has grown from 63 to 72+ tests since flight start (new tools, not consolidation).
- *Branch.* Recreated `flight/01-consolidation-and-hygiene` off `main` (`fe7abf0`). Prep commit `38ad841` carries the init-project methodology sync (migrations 004–009) and an operator `.mcp.json` ignore line — kept separate from flight work.
- *Protocol change.* Remaining legs run under the plugin-1.1.0 cadence: legs land uncommitted (`[LAND:leg]`), one flight-end review, one commit. Stale per-leg "Post-Completion Checklist" sections in the five remaining specs replaced with the current protocol line; citation audits appended.
- *Leg 10 drift.* Tool count is now 35; the offending sentence moved to `CLAUDE.md:242` ("other 32 tools"). Same fix (drop the number); spec annotated rather than rewritten.
- *Risk tiers.* All five remaining legs tiered **low**: 01/10/11/12 are single-line docs/comment/ignore edits; 09 touches only operator-run smoke scripts outside the unit net (`testpaths=["tests"]`), additive, no shared interface. No per-leg design review spawned; flight-end Reviewer covers the result.
- *Grouping.* Legs 01, 10, 11, 12 (trivial, disjoint lines) implemented by one Developer; leg 09 by a second Developer in parallel (disjoint files: smoke scripts vs `.gitignore`/`CLAUDE.md`/`playlists.py`). Each Developer writes its own flight-log entries and leg statuses.
- *Flight-end review.* One Reviewer (Sonnet) over all uncommitted changes (legs 01, 09–12): `[HANDOFF:confirmed]`, no blocking or non-blocking issues. HTTPS fallback host (filesamples.com) accepted — same scheme as the SoundHelix primary; HTTP candidates tried were dead or served HTML.
- *Out-of-scope finding.* `CLAUDE.md` Versioning says `__version__` is currently `"0.2.0"`; it is `"0.3.0"`. Not a flight finding — to be logged as a squawk after landing.
- *Landing.* All 12 legs `completed`; flight `landed`; mission criteria and Flight 1 checked off. Flight debrief pending (`/mission-control:flight-debrief`).

---

## Decisions

---

## Deviations

---

## Anomalies

---

## Session Notes
