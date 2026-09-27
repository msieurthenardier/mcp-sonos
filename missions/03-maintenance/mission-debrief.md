# Mission Debrief: Maintenance — Consolidation & Hygiene

**Date**: 2026-09-26
**Mission**: [Maintenance — Consolidation & Hygiene](mission.md)
**Status**: completed
**Duration**: 2026-06-02 - 2026-09-26
**Flights Completed**: 1 of 1
**Plugin version**: 1.1.0 (at debrief and for the mission's second half). The first half ran under an earlier release, which was not recorded; no version is known before 1.1.0.

## Outcome Assessment

### Success Criteria Results
| Criterion | Status | Notes |
|-----------|--------|-------|
| S-1 — `.env` gitignored | met | `git check-ignore .env` resolves; `.env.example` stays tracked; `.env` never committed |
| I-3 (+I-4) — one stale-coord retry helper, dead return gone | met | `mcp_sonos/_retry.py::with_stale_coord_retry`; closes debt carried since Mission 02 |
| I-5 — live-track dict extracted, reconciled vs `_track_state` | met | `PlaylistManager._live_track_dict`, with the difference from `_track_state` documented instead of forcing both into one helper |
| T-1 — `_say_all` sleep seam | met | `self._sleep`; suite 2.54s → 1.00s |
| T-5 — shared builder + constants | met | Landed in `tests/_builders.py` rather than `conftest.py` (better for per-call overrides) |
| T-6 — `worker_session` fixture, `:520` cleanup fixed | met | Context manager with `finally: mgr.stop` |
| T-3 — shared resume observable parametrized | met (nothing to fold) | Enumerating all 14 tests found every one pins a distinct behavior, so there was nothing to merge; coverage preserved |
| T-4 — skip-guard tests parametrized | met | 3 tests → 1 parametrized test with 3 named cases |
| T-7 — smoke scripts survive one host outage | met; not yet run on hardware | Primary + fallback pools via `_smoke_common.py`. The fallback host (filesamples.com) is HTTPS and hasn't been run on the speakers. |
| I-9 — "31 tools" phrasing reworded | met | Number removed (it had drifted again to "32" vs 35) |
| I-11 — duplicated `QUEUE_PARENT_ID` comment merged | met | Only its spec had been touched in `881d152`; the actual fix landed in `f1d0793` |
| I-12 — directory-listing guard codified | met | CLAUDE.md "When extending" |
| Suite passes, no behavior change | met | 78 passed, 0 failed, 0 skipped. 1.38–1.47s over 4 runs, no flakes. Of the growth from 63 to 78, 15 tests came from work outside this mission. |

### Overall Outcome
Achieved. All 12 actionable findings are resolved without changing behavior, and no assertion was weakened. The system is cleaner:
- One retry helper and one live-track reader where there were several.
- A shared test-builder base.
- A 60% faster suite.
- Smoke scripts that no longer depend on a single outside host.
- A public repo that can't leak `.env`.

The outcome was still the right goal at the end. The one caveat is the smoke fallback: it shipped, but it hasn't been played on the speakers.

## Flight Summary
| Flight | Status | Key Outcome |
|--------|--------|-------------|
| 01 Consolidation & Hygiene | completed | 12/12 legs. Legs 02–08 shipped 2026-06 in `881d152` (PR #8), bundled with the out-of-mission `reboot` tool. Legs 01 and 09–12 shipped 2026-09-26 in `f1d0793` (PR #9) after a ~3.5-month stall. |

## What Went Well
- **Behavior-preserving discipline held.** The flight refused two "dedup" moves that would have quietly changed behavior or dropped a regression guard:
  - Leg 03 kept the documented `""` vs `None` difference instead of forcing both readers into one helper.
  - Leg 07 enumerated all 14 resume tests and found a merge set of 0.

  The mission's "don't collapse coverage" constraint did exactly its job.
- **The debrief chain closed long-running threads.**
  - Mission 01 predicted that the stale-coordinator retry should be generalized. Mission 02 carried the two diverging copies as known debt. Mission 03 unified them.
  - The SoundHelix single point of failure (deferred by Mission 02) and the directory-listing guard (carried since Mission 01) were also closed.
  - The "Known Debt Carried Forward" section of the maintenance reports worked across all three cycles.
- **Up-front design review of all 12 specs** caught both real behavior traps (two different invalidation mechanisms; incompatible dict defaults) before any code was written.
- **Single-flight structure fit.** The operator would do it again. One leg per finding made the resume after the stall straightforward, and the legs could be batched into two parallel Developers at execution time.
- **Agent orchestration needed no human corrections** (operator's assessment). The flight-end review under the new cadence passed on the first cycle.

## What Could Be Improved
- **The mission went dormant for ~3.5 months with nothing prompting a return** (operator: "needed a nudge"). With half the legs merged via PR #8, the mission looked finished from the git side, and nothing surfaced the `in-flight` flight while three features and a version bump (0.3.0) landed on top.
- **Flight work shipped in a mixed commit whose message overclaimed.** `881d152` combined legs 02–08 with the `reboot` tool, a soco bump and a conftest fix, and said "legs 02-11". Leg 11 had never been implemented. The artifacts were right (leg statuses) and the commit message was wrong, and nothing cross-checked the two.
- **Documentation codification keeps trailing implementation by one cycle.** The directory-listing guard took two missions to get into CLAUDE.md. `_retry.py` immediately repeated the pattern (squawk 0002).
- **Numbers in prose keep drifting.** This has now happened in all three missions:
  - Mission 01: F11's "19 → 32" tool count.
  - Mission 03: I-9 "31 tools"; then 32 vs 35 during the stall; then the stale `"0.2.0"` version (squawk 0001).

  "Remove the number" is the durable fix. Nothing enforces it, though (no CI).
- **A larger doc error went unflagged by two maintenance inspections.** `CLAUDE.md:39` still says "No test framework, no linter configured. Smoke tests are the regression net." pytest has been there since Mission 01, the suite is now 78 tests, and it's the primary regression net. CLAUDE.md never says how to run it.

## Lessons Learned
- **Remove numbers from prose rather than correcting them.** For a value that must stay, reference its source of truth (`__init__.py`, `grep -c @mcp.tool`) instead of quoting it. A cheap local test is worth adding, modelled on `tests/test_version.py`, that fails if CLAUDE.md quotes `__version__` literally.
- **Extracting a helper while documenting where two structures differ is a legitimate dedup outcome.** Similar-looking structures with different consumers get a helper for the genuinely identical sites and a pointer comment for the rest.
- **Enumerate every test before consolidating.** A maintenance report's redundancy estimate can conflate "asserts the same observable" with "asserts only that observable". T-3's estimate of 2–4 mergeable tests was really 0.
- **Prefer plain builder modules over conftest fixtures** when callers need per-call overrides (`tests/_builders.py`).
- **Test-injection seams are now a repeated idiom:** `invalidate_speakers_cache` and `resolve_coordinator` DI (Mission 02), and `self._sleep` (Mission 03). Along with the shared-leaf-module pattern (`_urls.py`, `_retry.py`), they belong in CLAUDE.md "When extending".
- **Keep flight commits scoped to the flight.** Ship unrelated features separately even mid-flight. Bundling is what made the resume reconciliation necessary.
- **Features that landed outside any mission haven't been inspected yet.** `play_stream` and `playlist_from_page` (0.3.0) went in with no maintenance review. `playlist_from_page` is a new surface that fetches external web content, and the existing threat model may not cover it. The next routine-maintenance pass should treat both as being inspected for the first time.

## Methodology Feedback

Each finding restates an observation already recorded in the Flight 01 debrief's Methodology Observations. This mission has one flight, so the recurrence count is at most 1/1, and a later sweep should count each occurrence once. Cross-mission recurrence is noted where the Mission 01/02 debriefs show it.

1. **A dormant in-flight flight is never surfaced.**
   - *What happened:* Flight 01 sat `in-flight` with 7/12 legs landed for ~3.5 months. Nothing at session start or in any briefing surfaced it. The operator confirms a nudge would have prevented the stall.
   - *Expected:* a stale-in-flight alert, parallel to the squawk skill's staleness flags.
   - *Cost:* a full resume-reconciliation pass (branch recreated, 5 specs re-audited for citation and protocol drift, commit overclaim untangled) and 3.5 months of latency on a hygiene fix (`.env` exposure).
   - *Skill/phase:* agentic-workflow resume; SessionStart hook.
   - *Plugin version:* the stall began under a release before 1.1.0 (version not recorded); still unaddressed in 1.1.0 (the SessionStart hook reports drift only).
   - *Recurrence:* 1/1 flights (Flight 01 debrief, obs. 1).
   - *Destination:* **methodology observation**.
2. **Existing leg specs embed the commit protocol, and a migration that changes the protocol doesn't touch them.**
   - *What happened:* every leg carried the old "Post-Completion Checklist" (per-leg commit, `[COMPLETE:leg]`). After migration 008, the five legs not yet executed contradicted the crew prompts.
   - *Expected:* the migration updates, or at least flags, protocol text in legs not yet executed.
   - *Cost:* a manual rewrite of 5 specs. Without it, a Developer would have committed per leg against the new cadence.
   - *Skill/phase:* init-project migration 008 → agentic-workflow resume.
   - *Plugin version:* 1.1.0.
   - *Recurrence:* 1/1 flights (Flight 01 debrief, obs. 2).
   - *Destination:* **methodology observation**.
3. **Commit messages aren't derived from leg state.**
   - *What happened:* `881d152` claimed "legs 02-11"; leg 11 wasn't done.
   - *Expected:* the commit lists legs from their `landed`/`completed` statuses.
   - *Cost:* a false claim in history for 3.5 months, caught only by re-reading the working tree.
   - *Skill/phase:* agentic-workflow commit.
   - *Plugin version:* before 1.1.0 (not recorded). Under 1.1.0 the commit prompt still takes free text (the "artifact updates the Flight Director listed").
   - *Recurrence:* 1/1 flights (Flight 01 debrief, obs. 3).
   - *Destination:* **methodology observation**.
4. **A squawk deferred "until after landing" was dropped at landing.**
   - *What happened:* the version-drift finding was noted but not filed before `[COMPLETE:flight]`; the flight debrief caught it one step later.
   - *Cost:* minor, one step of delay.
   - *Skill/phase:* agentic-workflow Phase 3.
   - *Plugin version:* 1.1.0.
   - *Recurrence:* 1/1 flights (Flight 01 debrief, obs. 4).
   - *Destination:* **local lesson**. The cost was negligible and the debrief's squawk-conversion phase is designed to catch exactly this, so the methodology worked as intended one phase later.
5. **The init-project ARTIFACTS template has a find/replace bug.**
   - *What happened:* the template's Location rows and the "Triggered by" link read `mission-control:mission.md` (and similar) instead of `mission.md`.
   - *Cost:* hand-corrected during migration. A verbatim copy would record wrong artifact paths.
   - *Skill/phase:* init-project templates.
   - *Plugin version:* 1.1.0.
   - *Recurrence:* 1/1 flights (Flight 01 debrief, obs. 5).
   - *Destination:* **methodology observation**. It reproduces from the plugin alone, and the cost is a wrong artifact if not caught.
6. **Routine-maintenance inspections missed a stale central claim in CLAUDE.md** ("No test framework… Smoke tests are the regression net"), across two cycles.
   - *Expected:* documentation inspection checks CLAUDE.md's Commands section against the actual test setup.
   - *Cost:* a misleading project posture for every agent and contributor since Mission 01. No rework was observed.
   - *Destination:* **local lesson**. The inspection prompts are the project's routine-maintenance crew file to tune, and no observable rework resulted.

## Action Items
- [ ] Complete squawks [0001](../../squawks/0001-claude-md-stale-version.md) (stale `__version__` in CLAUDE.md) and [0002](../../squawks/0002-claude-md-retry-precedent.md) (`_retry.py` precedent) — one turnaround
- [ ] Squawk: fix `CLAUDE.md:39` "No test framework…" and add the pytest command to CLAUDE.md Commands (not yet logged)
- [ ] Hardware smoke run: `queue_smoke.py` + `reap_smoke.py`, including one run with the primary forced unreachable, to confirm the HTTPS fallback plays on Sonos
- [ ] Next routine-maintenance: treat `play_stream` / `playlist_from_page` (0.3.0) as uninspected. Check `playlist_from_page`'s external-fetch surface against the threat model. Carry forward I-6 (remainder), I-1, I-7, T-8, T-9.
- [ ] Consider a local test that fails if CLAUDE.md quotes `__version__` literally (enforces the drop-the-number rule without CI)
- [ ] CLAUDE.md "When extending": name the test-injection-seam idiom (`self._sleep`, DI callbacks). Could ride with squawk 0002.
- [ ] Process: ship out-of-flight features on their own branch/PR; when pausing a flight, add a Flight Director note so a resume doesn't depend on commit messages
