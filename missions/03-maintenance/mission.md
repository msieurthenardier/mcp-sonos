# Mission: Maintenance — Consolidation & Hygiene

**Status**: active

## Outcome
Resolve the codebase health issues identified in the 2026-06-02 maintenance
report: eliminate the duplicated source helpers and overlapping tests the
maintainer flagged as priorities, close the redundant/incorrect comments,
de-risk the SoundHelix smoke single-point-of-failure, and shut the `.env`
public-repo leak — all behavior-preserving, backed by the existing 63-test
suite. After this mission mcp-sonos has a single stale-coordinator retry helper,
a single live-track-read helper, a shared test-fixture base with no redundant
assertions, smoke scripts that survive a single external-host outage, and a
`.env` that can never be committed.

## Context
Second routine-maintenance cycle, following Mission 02 (Resilient Queue-Backed
Playback). The full report is at
[maintenance/2026-06-02.md](../../maintenance/2026-06-02.md). The inspection was
clean on security, types, git, and infrastructure, and discharged all four
prior test-coverage gaps. The "Maintenance Required" verdict rests on the three
quality axes the maintainer prioritized — code deduplication, redundant
comments, and overlapping tests — plus one cheap-but-irreversible hygiene gap
and the debrief-deferred SoundHelix smoke dependency. The maintainer chose to
collapse the Architect's recommended three flights into one flight with one leg
per finding.

## Success Criteria
- [ ] S-1 — `.env` is gitignored; `git check-ignore .env` resolves
- [ ] I-3 — the two stale-coordinator retry helpers are unified into one shared helper; the dead return value (I-4) is gone
- [ ] I-5 — the live-coordinator-read dict is extracted into one helper in `playlists.py`, reconciled against `controller.py` `_track_state`
- [ ] T-1 — `_say_all` has a `sleep_fn` injection seam; the say-all tests no longer pay the 1.0s sleep
- [ ] T-5 — a shared track/transport builder + constants live in `conftest.py`
- [ ] T-6 — a `worker_session` fixture replaces the ×4 boilerplate and fixes the missing-`mgr.stop` cleanup at `test_queue_path.py:520`
- [ ] T-3 — the shared resume observable is parametrized; behavior-specific resume tests preserved
- [ ] T-4 — the three skip-guard tests are parametrized
- [ ] T-7 — `queue_smoke.py` + `reap_smoke.py` survive a single external-host outage via a fallback URL
- [ ] I-9 — the `CLAUDE.md` "31 tools" phrasing is reworded
- [ ] I-11 — the duplicated `QUEUE_PARENT_ID` comment block is merged
- [ ] I-12 — the `audio_host.py` directory-listing guard is codified in `CLAUDE.md` "When extending"
- [ ] The full test suite still passes (63 tests, adjusted count after consolidation) with no behavior change

## Stakeholders
Maintainer (msieurthenardier). Self-deployed on home LAN. No external users.

## Constraints
- **Behavior-preserving only.** Every source refactor (I-3, I-5) and test
  consolidation (T-3, T-4, T-5, T-6) must leave runtime behavior unchanged,
  verified by the existing suite. No new tools, no contract changes.
- **Do not collapse coverage.** T-3/T-4 parametrize only the *shared observable*;
  the tests pinning distinct behaviors (`play_url` blocking + timeout cap,
  `play_file` delegation, non-default `play_mode`, seek-failure/at-zero guards)
  stay standalone.
- **No committed test MP3** (T-7). Use a fallback external URL — public MP3s are
  abundant.
- Anything touching groups goes through `_coordinator_of` / `_group_members_of`
  (CLAUDE.md invariant).
- The unified retry helper (I-3) must preserve both call sites' contracts: the
  controller path needs the fresh coordinator returned; the queue path needs the
  injected `invalidate_speakers_cache` callback.

## Environment Requirements
- Existing local Python venv at `<repo-root>/.venv` (suite requires it active —
  bare `python3` fails with `ModuleNotFoundError: soco`)
- Live Sonos hardware only for the smoke scripts (T-7) — the unit suite is
  hardware-free
- No CI to satisfy

## Open Questions
N/A — all findings are concrete fixes derived from the maintenance report.

## Known Issues
N/A — none open at mission start.

## Flights

> **Note:** The maintainer chose a single-flight structure (one leg per finding).

- [ ] Flight 1: Consolidation & Hygiene — all 12 actionable findings as atomic
  legs (hygiene → source dedup → test seam/dedup/parametrization → smoke
  resilience → comment fixes)
