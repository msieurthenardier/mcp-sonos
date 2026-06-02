# Flight Debrief: Documentation + Smoke Coverage

**Date**: 2026-06-02
**Flight**: [Documentation + Smoke Coverage](flight.md)
**Status**: landed
**Duration**: single session (2026-06-02)
**Legs Completed**: 2 (docs; smoke-and-hygiene)

## Outcome Assessment

### Objectives Achieved
The Flight 1+2 queue work is now documented everywhere an agent or reader looks — README
(Playlist limitations rewritten for the two-engine/reap reality; queue in What-it-does/
Tools/Architecture; `PLAY_URL_RESUME_TIMEOUT_SECONDS`; the agent system-prompt section
updated for the `engine` discriminator, reap-survival control, and mid-track auto-resume,
with the obsolete manual-resume dance corrected), CLAUDE.md (two-engine architecture,
`PlaylistManager` DI params, `engine` key, `QUEUE_PARENT_ID` audit pointer, the
`status.title`/`say("all")`/`next`-`previous` caveats), and `.env.example`. A two-phase
`reap_smoke.py` provides operator-runnable reap-survival regression. The Flight 2 debrief
hygiene items (stale `play_url` docstring, `# NOTE:` comments, residual "start-of-track"
wording) are cleared.

### Mission Criteria Advanced
- **Q7** — docs + smoke — ✅ closed. **This closes Mission 02 (Q1–Q7 all met).**
- All checkpoints met. Suite unchanged at **63 tests** (docs/comments only).

## What Went Well
- **Front-loading the design-reviewed claims verbatim into the docs leg spec** removed
  implementer discretion on the wording that mattered (mid-track-best-effort, `say("all")`
  ungrouped, `status.title` present-but-unreliable). The independent Reviewer then verified
  every claim against code — zero inaccuracies landed. For a docs flight, "design-review the
  claims against code at planning, then assert them verbatim" is the winning shape.
- **The flight-level Architect review caught a stale `play_url` docstring** (pre-mid-track-
  pivot) before any doc was written — the review's whole value here was accuracy, not design.
- **Two-phase `--load`/`--control` smoke** cleanly models "test that survives process death"
  (one process can't reap itself) — a reusable pattern.
- Clean execution: no deviations, no anomalies, both legs faithful to spec.

## What Could Be Improved

### Technical / Knowledge
- **Doc-drift risk across three locations.** The two-engine + agent guidance now spans
  README, CLAUDE.md, and the (verbose, 11-item) system-prompt section — they can drift
  independently. Highest risk is the system-prompt items going stale when a new `playlist_*`
  tool or engine change lands. Mitigation below.
- **SoundHelix single-point-of-failure.** All four smoke scripts (`smoke_test`,
  `playlist_smoke`, `queue_smoke`, `reap_smoke`) use SoundHelix MP3 URLs as the known-good
  external source — no SLA. If it goes offline, all four degrade at once.
- **`reap_smoke.py` minor fragility**: the Phase-2 liveness assertion is slightly over-broad,
  and there's no inter-phase wait hint (a runner could start `--control` before the speaker
  actually begins playing). Cosmetic; the docstring mentions waiting.
- **F1 debrief test gaps still open after F3**: `play_mode`-before-`play_from_queue` ordering
  (actually added in F2 Leg 2 — verify), `status()` no-session *stopped* path, and the
  `SoCoSlaveException` retry branch in the controller's `_play_uri_with_stale_coord_retry`
  (zero coverage). All 3–5-line tests; fold into the next playlists/controller change.

### Test Metrics
**63 passed, 0 failed, 0 skipped, ~3.0s, no flakes** — unchanged from Flight 2 (correct for a
docs-only flight; the root-level smoke script is not collected by `testpaths=["tests"]`).
Baselines: F1 41 / ~0.9s, F2 63 / ~2.6s. The +0.4s over F2 is process-startup variance, not a
new slow test. (The `_say_all` ~1.5s hardcoded-sleep outlier noted in the F2 debrief persists.)

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| _None_ — flight executed the pre-agreed design faithfully | — | — |

## Key Learnings
- For docs flights, the dominant risk is **inaccuracy**, and the antidote is a planning-time
  Architect pass that cross-references every planned claim against code, then asserting those
  claims verbatim in the leg spec. This caught a stale docstring and produced zero-inaccuracy docs.
- A clean three-flight mission arc: **build (gated by HW spikes) → harden + control (gated) →
  document**. The debrief→next-flight action-item loop carried cleanly across all three.

## Recommendations
1. **Mission 02 is ready to close** — run `/mission-debrief` next. All Q1–Q7 met, all flights completed.
2. **Anti-drift convention**: when any future flight adds/changes a `playlist_*` tool or engine
   behavior, make "update README system-prompt items + CLAUDE.md two-engine section" an explicit
   leg acceptance criterion — not just "update README."
3. **Maintenance candidate**: reduce the SoundHelix single-point-of-failure across the four
   smokes (a fallback URL, or host a tiny stable test MP3). Good `/routine-maintenance` item.
4. **Fold the lingering F1 test gaps** (`status()` no-session stopped; `SoCoSlaveException`
   retry branch) into the next `playlists.py`/`controller.py`-touching change.
5. **Minor**: tighten `reap_smoke.py`'s liveness assertion + add an inter-phase wait hint.

## Action Items
- [ ] Run `/mission-debrief` to close Mission 02
- [ ] (Maintenance) De-risk the shared SoundHelix dependency across the smoke scripts
- [ ] (Next code change) Add the open unit tests: `status()` no-session stopped; controller `SoCoSlaveException` retry branch
- [ ] (Convention) System-prompt + CLAUDE.md update as an explicit AC on future tool/engine changes
- [ ] (Minor) `reap_smoke.py`: tighten liveness check + inter-phase wait note
