# Flight Debrief: Consolidation & Hygiene

**Date**: 2026-09-26
**Flight**: [Consolidation & Hygiene](flight.md)
**Status**: landed
**Duration**: 2026-06-02 - 2026-09-26 (legs 02–08 executed 2026-06-02; ~3.5-month stall; legs 01, 09–12 executed 2026-09-26)
**Legs Completed**: 12 of 12
**Plugin version**: 1.1.0 (second half and this debrief). First half (legs 02–08) ran under an earlier plugin release whose version was not recorded — unrecorded before 1.1.0.

## Outcome Assessment

### Objectives Achieved
All 12 actionable findings from the 2026-06-02 maintenance report were resolved, behavior-preserving, with no assertion weakened:
- **Source dedup**: one stale-coordinator retry helper (`mcp_sonos/_retry.py::with_stale_coord_retry`) replaces two ~80%-identical bespoke copies, with both call sites' divergent contracts (return value, invalidation mechanism) preserved through parameterization; the dead return value (I-4) disappeared as designed. One `PlaylistManager._live_track_dict` replaces three inline dict builds, with a documented divergence from `controller._track_state` instead of a forced merge.
- **Test seam + consolidation**: `_say_all` sleep injection seam; shared `tests/_builders.py` (builder + constants + `worker_session` context manager, closing the missing-`mgr.stop` cleanup gap); three skip-guard tests → one parametrized test with named cases. T-3 enumerated all 14 resume tests and found a merge set of 0 — every test pins a distinct behavior.
- **Smoke resilience**: `queue_smoke.py`/`reap_smoke.py` select a reachable external MP3 pool at runtime (SoundHelix primary, filesamples.com fallback) via new root-level `_smoke_common.py`; `reap_smoke --control` never probes.
- **Hygiene/docs**: `.env` gitignored; drifting tool count removed from CLAUDE.md; duplicated `QUEUE_PARENT_ID` comment merged; audio-host directory-listing guard codified in CLAUDE.md "When extending".

### Mission Criteria Advanced
All 13 Mission 03 success criteria (S-1, I-3/I-4, I-5, T-1, T-3, T-4, T-5, T-6, T-7, I-9, I-11, I-12, suite green) — this was the mission's only flight.

## What Went Well
- **Consolidated up-front design review paid off.** One Developer design-reviewed all 12 specs before implementation and pre-corrected the two real behavior-preservation traps: leg 02's two different invalidation mechanisms, and leg 03's structurally incompatible dict shapes (`""` vs `None` defaults). The shipped code handles both correctly.
- **Declining to over-consolidate.** Leg 03 (extract-with-documented-divergence) and leg 07 (full enumeration → merge set 0) both refused a "dedup" that would have been a silent behavior change or a lost regression guard. The flight's constraint "over-keeping costs lines; over-collapsing loses a regression guard" worked as intended.
- **Leg 04 was the highest-value leg per line changed**: one injectable `self._sleep` cut suite wall-clock 2.54s → 1.00s (~60%).
- **Atomic per-leg specs + flight log made the 3.5-month resume tractable.** State was reconciled leg-by-leg against the live tree rather than reverse-engineered from a mixed diff; the reconciliation caught that leg 11 had been claimed but never implemented.
- **Parallel Developers on disjoint files** (legs 01/10/11/12 vs leg 09) finished the second half in one sitting with no flight-log edit conflicts.
- **Leg 09 respected the two-phase reap architecture unprompted-in-detail**: the probe lives only in `phase_load()`, so `--control` stays independent of `--load`'s choice.

## What Could Be Improved

### Process
- **The flight stalled for ~3.5 months** (operator: "lost track of the flight"). Nothing surfaced an `in-flight` flight with half its legs landed while unrelated feature work (reboot, play_stream, playlist_from_page, 0.3.0) merged on top.
- **Flight work was merged mid-flight bundled with out-of-flight work.** `881d152` (PR #8) carried legs 02–08 alongside the `reboot` tool, a soco bump, and a conftest flake fix, and its message claimed "legs 02-11" when leg 11's code was never changed (only its spec). The overclaim stood unnoticed until the resume reconciliation.
- **The out-of-scope version-drift finding wasn't squawked at landing.** The flight log said "to be logged as a squawk after landing"; it hadn't been by debrief time. Handled in this debrief (see Action Items).

### Technical
- No technical debt introduced by the flight's own work.
- `_smoke_common.select_track_pool`'s total-outage fallthrough is verified only by a one-off dry-run in the flight log — no repeatable check. Acceptable under the project's "smoke is manual" posture, but it's the one new logic path with zero automated guard.
- **The fallback host is HTTPS and untested on hardware.** filesamples.com was chosen after plain-HTTP candidates proved dead or served HTML; same scheme as the SoundHelix primary, but CLAUDE.md flags HTTPS as fragile on Sonos. Operator confirms no hardware smoke run yet.
- Finding I-6 (smoke-script scaffolding duplication) is only partially discharged: `_smoke_common.py` holds the track pools + selector, but `pp()`/env-default boilerplate remains duplicated.

### Documentation
- CLAUDE.md Versioning says `__version__` is `"0.2.0"`; code is `"0.3.0"`. Same class of drift as I-9 (a hardcoded number in prose).
- CLAUDE.md "When extending" names `_urls.py` as the single example of the shared-helper-module pattern; `_retry.py` is now a second precedent and isn't mentioned.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| T-5 builder in `tests/_builders.py`, not `conftest.py` | Plain functions with call-time overrides compose better than fixtures for legs 07/08; constants only existed in one file | Yes — prefer plain builder modules over conftest fixtures when callers need per-call overrides |
| T-3 merge set 0 (estimated ~2–4) | Report conflated "asserts the same observable" with "asserts *only* that observable" | Yes — full enumeration before any "consolidate overlapping tests" leg |
| Legs 02–08 shipped mid-flight in a mixed commit | Operator wanted the reboot tool out; flight WIP rode along | No |
| Leg 10's target sentence and count drifted (31/32 → 32/35) | 3.5-month gap + intervening tool additions | Yes — fix drifting numbers by removing them, not correcting them |
| Commit/review cadence switched mid-flight (per-leg → flight-end) | Plugin upgrade to 1.1.0 (migration 008) between halves | N/A (methodology change) |
| `_smoke_common.py` created (optional in spec) | Natural home for pools + selector shared by two scripts | Yes (already endorsed by spec) |

## Key Learnings
- **Hardcoded numbers in prose drift, repeatedly.** The tool count drifted twice inside this one flight, and the version string drifted during the stall. "Remove the number" is the durable fix; "correct the number" just resets the clock.
- **Extract-with-documented-divergence is a legitimate dedup outcome.** Two similar-looking structures with different consumers should get a helper for the genuinely identical sites plus a pointer comment — not a forced shared base.
- **Line-number citations rot; symbol citations don't.** Every leg's line refs had drifted by implementation time and needed a correction pass (twice — once at design review, once at resume).
- **Test metrics** (seed + comparison): flight start 63 tests / ~2.5–3.0s → after leg 04: 63 / 1.00s → flight end: **78 passed, 0 failed, 0 skipped, 1.38–1.47s across 4 runs, no flakes**. The flight's own net test-count effect was neutral by design; +15 came from out-of-flight work (`test_reboot.py` 9, plus 0.3.0 feature tests e.g. `test_extract.py` 6). Per-file: `test_queue_resume.py` 14 (0.66s, slowest), `test_queue_path.py` 26 (0.21s), `test_urls.py` 13, `test_reboot.py` 9, `test_extract.py` 6, `test_tts_verify.py` 4, `test_version.py` 3, `test_say_coordinator.py` 2, `test_playlists_takeover.py` 1. Slowest single setup 0.05s. `pytest-randomly` isn't installed, so `881d152`'s "stable across 20 randomized runs" claim can't be re-verified.

## Methodology Observations

1. **In-flight flight went dormant with no signal.** *Skill/phase*: agentic-workflow (between legs) / session start. *What happened*: Flight 01 sat `in-flight` with 7/12 legs landed for ~3.5 months while unrelated work merged on top; nothing (SessionStart, briefing) surfaced it. *Expected*: an in-flight flight with no activity for N days gets surfaced when a session starts in the project. *Cost*: a full resume-reconciliation pass (branch recreated, 5 specs citation-audited, leg 10 re-scoped for drift, commit-message overclaim untangled). *Plugin version*: unrecorded before 1.1.0 (stall began under the prior release).
2. **Leg specs baked the commit protocol into their bodies.** *Skill/phase*: flight (leg authoring, via the old ARTIFACTS leg template's "Post-Completion Checklist") → agentic-workflow resume. *What happened*: all 12 specs ended with "commit + signal `[COMPLETE:leg]`"; after migration 008 changed the cadence, the five unexecuted specs contradicted the crew prompt and would have made a Developer commit per leg. *Expected*: migrations that change protocol either touch existing unexecuted leg artifacts or the resume path flags protocol text in them. *Cost*: Flight Director manually rewrote the section in 5 specs. *Plugin version*: 1.1.0 (migration 008).
3. **Commit message claimed legs that hadn't landed; nothing cross-checked.** *Skill/phase*: agentic-workflow (commit). *What happened*: `881d152` said "legs 02-11"; leg 11 had only a spec edit. Leg statuses were `landed` for 02–08 only, so the artifacts were right and the commit message wrong. *Expected*: the commit step derives the leg list from leg statuses rather than free text. *Cost*: a latent false claim in history for 3.5 months; caught only by re-reading the tree at resume. *Plugin version*: unrecorded before 1.1.0.
4. **Out-of-scope finding deferred to "squawk after landing" then not filed.** *Skill/phase*: agentic-workflow (2d → Phase 3). *What happened*: the Flight Director noted CLAUDE.md version drift during review, logged "squawk after landing", and landed without filing it; the debrief Developer found no squawk. *Expected*: Phase 3 flight completion checks for deferred-squawk notes in the flight log and files them before `[COMPLETE:flight]`. *Cost*: minor — caught one step later by this debrief. *Plugin version*: 1.1.0.
5. **init-project template has a find/replace bug.** *Skill/phase*: init-project (ARTIFACTS template). *What happened*: `templates/ARTIFACTS-files.md` Location rows read `missions/{NN}-{slug}/mission-control:mission.md` (also `flight.md`, `flight-debrief.md`, `mission-debrief.md`, and a "Triggered by" link). *Expected*: `mission.md` etc. *Cost*: hand-corrected during the migration; a project copying the template verbatim would get wrong artifact paths. *Plugin version*: 1.1.0.

## Recommendations
1. **Fix the CLAUDE.md version drift by removing the number** (point at `mcp_sonos/__init__.py` instead of quoting it) — same fix pattern as I-9. Squawk.
2. **Run `queue_smoke.py` and `reap_smoke.py` on hardware**, once normally and once with the primary forced unreachable, to confirm the HTTPS filesamples.com fallback actually plays on Sonos. If it doesn't, look for a plain-HTTP host.
3. **Keep flight commits scoped to the flight.** Ship unrelated features on their own branch/PR even when a flight is mid-way; if a flight must pause, record the pause in the flight log so resume doesn't depend on commit messages.
4. **Next maintenance cycle: finish I-6** by moving the remaining `pp()`/env-default scaffolding into `_smoke_common.py`, and consider a tiny unit test for `select_track_pool`'s total-outage fallthrough.
5. **Name `_retry.py` as a second example** in CLAUDE.md "When extending" alongside `_urls.py`.

## Action Items
- [ ] Squawk [0001](../../../../squawks/0001-claude-md-stale-version.md): CLAUDE.md Versioning quotes stale `__version__` (`"0.2.0"` vs `"0.3.0"`) — remove the literal
- [ ] Hardware smoke run of `queue_smoke.py` + `reap_smoke.py`, including forced-fallback
- [ ] Squawk [0002](../../../../squawks/0002-claude-md-retry-precedent.md): mention `_retry.py` as a second shared-helper precedent in CLAUDE.md "When extending"
- [ ] Next maintenance cycle: finish I-6 (smoke scaffolding) + optional `select_track_pool` unit test
