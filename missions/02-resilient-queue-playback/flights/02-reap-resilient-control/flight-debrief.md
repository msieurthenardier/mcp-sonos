# Flight Debrief: Reap-Resilient Control Surface

**Date**: 2026-06-02
**Flight**: [Reap-Resilient Control Surface](flight.md)
**Status**: landed
**Duration**: single session (2026-06-01 → 2026-06-02)
**Legs Completed**: 5 (Legs 1–5; Leg 6 optional — not run)

## Outcome Assessment

### Objectives Achieved
The `playlist_*` control tools now operate against **live coordinator state** when there
is no in-RAM `_sessions` entry, so they keep working after the MCP is reaped and
respawned (Q4). `say` and single-coordinator `play_url` snapshot an active native queue,
play the clip, and **resume the queue mid-track** afterward (Q6) — an announcement no
longer silently ends queue playback. The Flight 1 interim contract gap (control tools
reporting `running:false` over a live queue) is closed. All five Flight 1 debrief action
items were cleared in the same surface.

### Mission Criteria Advanced
- **Q4** — stateless `status`/`next`/`previous`/`stop` after reap+respawn — ✅ HW-verified
- **Q6** — `say`/`play_url` takeover + resume (mid-track) + grouping semantics — ✅ HW-verified
- Deferred: **Q7** (docs/smoke) → Flight 3
- All checkpoints met. Suite: **63 tests, 100% pass, ~2.6s**.

## What Went Well
- **Two hardware gates de-risked the empirical unknowns.** Leg 3 (formal hard gate) proved
  `play_uri` preserves the queue, resume-from-STOPPED works, and the 1-based→0-based
  off-by-one — before any takeover code. The ad-hoc Leg 5 seek spike (run in-session, not a
  formal leg) proved the host honors HTTP range requests, enabling mid-track resume.
- **Operator-in-loop HAT revision worked as designed.** Start-of-track was a conservative
  planning placeholder; the Leg 5 HAT surfaced the UX was wrong, the seek spike confirmed
  feasibility, and the fallback design (`try: seek() except: pass`) made mid-track resume
  zero-risk. The pivot cost ~10 lines + 3 tests and was recorded across flight-log FD Notes
  + the reopened Leg 4 + flight.md — clean artifact trail.
- **Cleared the Flight 1 debrief backlog** (stop actually stops; status/next/previous live;
  cache-flush parity; artist/album not title; dead-code removal; missing tests) — debrief
  → next-flight feedback loop closed.
- **Clean seams.** `has_active_session(speaker_uid)` exposes exactly what the controller
  needs without leaking session internals; `_with_queue_resume` is hardware-free testable
  (snapshot/run/wait/resume, each phase guarded). 14 helper tests assert real behavior.
- **Layered review caught the right things** (play_file inherits the contract; s.uid keying;
  SoCoFake `_track` clobber) before implementation.

## What Could Be Improved

### Process
- **Reopened-leg supersession.** When Leg 4 was reopened for the mid-track pivot, the new
  criteria were *appended* with a notice block, but the original Leg 4 criteria + the Leg 5
  objective still read "start-of-track." A reader following the original text would build
  incomplete behavior. Convention to adopt: strike/supersede superseded criteria, not just
  append. (Fix the residual "start-of-track" lines when Flight 3 touches these artifacts.)
- **Cross-method consistency missed at spec time.** "engine key everywhere" was a stated DD
  but Leg 1 left the worker-session returns untagged; it landed as a post-Leg-2 review fix.
  A one-line consistency checklist in the leg template ("do all return paths carry the
  discriminator fields?") would catch this class earlier.

### Technical
- **`coord_holder`/stale-coord interaction** (reviewer-flagged benign): `_with_queue_resume`
  captures `coord` at snapshot time; if `say()`'s stale-coord retry swaps `coord_holder[0]`
  inside `run_clip`, the wait+resume run on the pre-retry coord. Same physical device, best-
  effort wrapper swallows the corner case — safe, but the call site lacks a `# NOTE:`.
- **`playlists.py` live-state reads duplicate the `_track_state` pattern** (controller.py).
  Fine for one reader; if a third appears, extract `_live_track_snapshot(coord)` or promote
  `_track_state` to an importable module-level helper.
- **`play_mode` restore sits inside the outer best-effort try/except** — if `play_from_queue`
  fails, `play_mode` isn't restored (intentional; no position to restore to) but uncommented.
- **`next`/`previous` no-session lack a stale-coord retry** (unlike `say`); a `SoCoSlaveException`
  is swallowed and the advance is silently lost. Consistent with best-effort posture; document.

### Test Metrics
**63 passed, 0 failed, 0 skipped, ~2.56s, no flakes** (venv required). Baseline (Flight 1
debrief): 41 tests, ~0.9s. **Delta: +22 tests (+54%), +1.66s.** The count tracks exactly to
Flight 2 additions (Leg 1 +4 net, Leg 2 +2, post-review +2, Leg 4 +11, mid-track reopen +3).
Modules: `test_queue_path.py` (26), `test_queue_resume.py` (14), `test_urls.py` (13),
`test_tts_verify.py` (4), `test_version.py` (3), `test_say_coordinator.py` (2),
`test_playlists_takeover.py` (1). The single ~1.5s outlier is `test_say_all_no_resume`,
which hits `_say_all`'s hardcoded `time.sleep(1.0)` topology-settle (not patchable without a
`sleep_fn` injection). Not a flake; flag for a sleep-injection refactor if the suite grows.

### Documentation (all → Flight 3 / Q7)
README + CLAUDE.md + agent system prompt need: `play_url`'s blocking-contract change +
`PLAY_URL_RESUME_TIMEOUT_SECONDS` config; the `say("all")` group-destruction limitation
(stronger than "best-effort" — it's destructive); post-reap identity limitation; the
`engine` discriminator meaning; two-engine architecture; `PlaylistManager` DI params
(`host_ip`/`audio_port`/`resolve_coordinator`/`invalidate_speakers_cache`); `QUEUE_PARENT_ID`
audit-trail pointer; and a note that `status().title` is unreliable for queued items
(use `artist`/`album`).

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| Start-of-track → **mid-track** resume (Leg 4 reopened) | Leg 5 HAT showed start-of-track was wrong UX; seek spike proved feasibility | The *process* (operator-in-loop HAT revision w/ flight-log + leg-reopen + flight.md update) — yes |
| `engine: "worker"` added via post-Leg-2 review fix | "engine everywhere" DD not fully applied in Leg 1 | Add a return-shape consistency checklist to leg template |
| `play_url` resume not live-tested | A live clip blocks the MCP for the full duration; shares the identical helper proven via say-live | Yes — unit + one-path-live is sufficient when paths share a helper |
| Leg 5 seek spike run ad-hoc (not a formal leg) | Empirical question emerged mid-HAT; ~10 min to answer | Yes — not every empirical check needs a formal leg, but record it in the log |

## Key Learnings
- **Hard-gate-spike-before-empirical-feature** is now proven twice (Flight 1 metadata gate,
  Flight 2 takeover gate + seek spike). Any feature resting on Sonos/SoCo firmware behavior
  not confirmed by docs or a prior flight should be gated behind a throwaway HAT spike before
  implementation. Worth promoting to a first-class pattern in the leg-spec format.
- **Conservative planning placeholders + operator-in-loop revision** beat trying to settle
  every UX detail at planning time — *when* the mechanism is gated first so the revision is
  cheap and safe.
- The debrief→next-flight action-item loop demonstrably works: every Flight 1 debrief item
  was a Flight 2 deliverable, and the Flight 1 Known Issue is now resolved.

## Recommendations
1. **Flight 3 = docs + smoke (Q7) + artifact cleanup.** Document the items listed above; fix
   the residual "start-of-track" wording in Leg 4/Leg 5 specs; add a reap-survival smoke test
   (load queue → exit → fresh process asserts `engine: native_queue` via `playlist_status`).
2. **Add `# NOTE:` comments** at the `coord_holder` call site and the `play_mode`-restore site
   so the intentional best-effort corners are self-documenting (fold into Flight 3 or the next
   playlists/controller-touching change).
3. **Consider a behavior-test spec** for the reap-survival + say-resume flow as the Q7 smoke
   deliverable — valuable regression for HAT-only behavior, *if* the Executor can get reliable
   live-hardware access. Decision point for Flight 3.
4. **Leg-template improvements**: a return-shape consistency checklist; a first-class
   "hardware spike gate" leg type.
5. **Defer (not now)**: extract a shared `_with_stale_coord_retry(call_fn)` if a third retry
   site appears; inject `sleep_fn` into `_say_all` if suite time grows.

## Action Items
- [ ] Flight 3: document `play_url` blocking contract + `PLAY_URL_RESUME_TIMEOUT_SECONDS`; `say("all")` destructive limitation; post-reap identity; `engine` discriminator; two-engine arch; `PlaylistManager` DI params; `QUEUE_PARENT_ID` audit pointer; `status().title` unreliability
- [ ] Flight 3: reap-survival smoke test (Q7); decide on a behavior-test spec for the flow
- [ ] Flight 3: fix residual "start-of-track" wording in Leg 4 (original criteria) + Leg 5 objective
- [ ] Code hygiene (next playlists/controller change): `# NOTE:` at `coord_holder` + `play_mode`-restore; document `next`/`previous` no-session best-effort (no stale-coord retry)
- [ ] Watch: extract live-state-read helper if a third reader appears in `playlists.py`
