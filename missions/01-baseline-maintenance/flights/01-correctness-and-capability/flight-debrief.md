# Flight Debrief: Correctness and Capability Hardening

**Date**: 2026-05-18
**Flight**: [Correctness and Capability Hardening](flight.md)
**Status**: landed
**Duration**: 2026-05-18 (planning + execution same day, ~4 hours wall-clock from `/flight` invocation to draft PR)
**Legs Completed**: 6 of 6

## Outcome Assessment

### Objectives Achieved
All six maintenance findings (F1, F2, F3, F5, F12, F14) landed cleanly. The real correctness bug (F1) is fixed. The threat-model-crossing capability (F2) is scoped. The input-validation surface is hardened across three layers (F14 defence-in-depth via `_urls.validate_http_url`).

### Mission Criteria Advanced
6 of 14 mission success criteria ticked. Flight 1 of 4 marked complete in the mission's flight list. Mission remains `active` with Flights 2–4 still `ready`.

## What Went Well

- **Phase 1b reconnaissance paid off twice.** Caught F2's serve-root sharing (TTS WAVs + `play_file` copies in one directory — the original maintenance report hadn't distinguished surfaces, so the architect's "filter at serve root" framing would have broken TTS). Also caught F5's helper-returns-strings contract — Architect picked option A based on the recon evidence.
- **Design-review-per-leg via `/agentic-workflow` caught several real issues** before implementation: F2 env-read location (controller vs audio_host), F2 lazy-vs-eager validation, F2 AC tightening (`.env.example` placement, README anchor), F3 covering both `preferred` and env paths in port validation, F4 leg slip (`self._group_members_of`), F6 `playlist_add_many` strategy decision, F6 `netloc` check addition.
- **`_urls.py` defence-in-depth pattern is the strongest architectural outcome.** One validator, three import sites (tool/controller/playlist). Codifying the pattern catches non-MCP callers without re-stating policy. Worth standardizing as a project convention.
- **Per-leg commits succeeded** despite the complexity (three legs touched `controller.py`, three touched `audio_host.py`). The split Developer agent stayed disciplined and each commit compiles cleanly when checked out incrementally — preserving `git bisect` value.
- **Live-hardware smoke baseline at flight start.** Leg 01's Developer caught the convention and recorded a clean baseline (`smoke_test.py` + `playlist_smoke.py` both green on 5 speakers at 2026-05-18T13:30Z), establishing a clear "what we started from."

## What Could Be Improved

### Process

- **Snippet prescriptions in leg specs should be verified against call-site conventions, not just symbol existence.** Leg 04 specified `self._group_members_of(coord)`, but `_group_members_of` is module-level (all five other call sites use the bare form). The implementing Developer caught it in seconds — but the slip illustrates a recon-pass gap: confirming a symbol exists isn't the same as confirming the call shape.
- **Hardware-dependent acceptance criteria should be pre-marked as deferable.** Legs 02, 04, 05 each had ACs that required live hardware to verify end-to-end. Each got handled correctly (deferred or code-path-verified), but the pattern was applied inconsistently — sometimes the AC noted "deferred to flight Post-Flight", sometimes the developer made the call inline. A leg-template convention would be cleaner.
- **The Leg 05 anomaly hypothesis ("Sonos household topology") was wrong** and the flight didn't plan a "re-run smoke after household-state reset" gate that would have isolated the issue immediately. Post-debrief reproduction (next section) proved the failure is a real bug, not transient state.

### Technical

- **F1 lands without a regression test.** Future contributors can re-break `session.coordinator_name` and only catch it on the live takeover path that smoke tests don't exercise. The bug is exactly the shape a unit test against a SoCo fake would catch hardware-free. This is the canonical first target for Flight 4 (test scaffolding).
- **`server.py` `HttpUrl` alias is half-adopted.** Defined at `server.py:46` but the two consumer tools inline `AfterValidator(...)` instead of using the alias, because chaining `Field(description=...)` after the alias is awkward. Either delete the alias or find a Pydantic 2 pattern that combines both. Small follow-up.
- **`_say_all` (`controller.py:336-366`) still uses inline `for s in speakers` with per-call try/except.** Same anti-pattern that F5 cleaned up in `say()`. Routing through `_group_members_of` / `_coordinator_of` would tighten consistency, though the unjoin/partymode sequence is its own beast.
- **F2 `media_root.is_dir()` is checked lazily per call**, not at startup. Acceptable, but a startup-time pre-flight warning if `AUDIO_MEDIA_ROOT` is set and missing would catch typos before the first `play_file` call.

### Documentation

- **CLAUDE.md should codify two patterns this flight emerged**:
  - The `_urls.py` defence-in-depth idiom (single validator, tool + controller + manager call sites).
  - "New env vars: parse eagerly at `__init__`, validate lazily at first use" — the pattern used for `AUDIO_MEDIA_ROOT`.
- **The directory-listing block in `audio_host.py:Handler` is invisible to future contributors** until they read the leg or commit. CLAUDE.md should note: "Future contributors adding new file-serving paths shouldn't accidentally re-enable enumeration."
- **`playlist_add_many` has subtly-different rejection messages** at the tool surface (`ValueError`) vs the playlist manager (`PlaylistError`). Documented in Leg 06 notes but not user-facing.

## Anomaly Investigation — `smoke_test.py` `say()` Failure

**Status**: confirmed pre-existing bug, NOT a Flight 01 regression. Promoted to mission-level Known Issues.

Leg 05's flight-log entry hypothesized "Sonos household grouping topology" was responsible for `say()` failing with `play_uri can only be called/used on the coordinator in a group`. Re-running `smoke_test.py` during this debrief reproduced the failure with `list_groups` showing every speaker as its own singleton coordinator — so Kitchen IS the coordinator at call time, and the household-topology hypothesis is **wrong**.

**Where the failure happens**: `controller.py:328` — `coord.play_uri(url, title=f"Say: {text[:40]}")`. The preceding `_resolve_coordinator(target)` returned `(s, coord)` where SoCo's group state apparently disagrees with Sonos firmware's view of "who is the coordinator." Candidate root causes:

1. The cached SoCo for "Kitchen" has stale `is_coordinator` after a recent topology change; SoCo's `group.coordinator` view diverged from firmware reality.
2. `_resolve_coordinator` returns the speaker itself in the `coordinator=None` lull (per `_coordinator_of` design), but Sonos rejects `play_uri` on a non-coordinator even when SoCo's view says otherwise.

**This is not a Flight 01 regression**: Leg 04's `say()` refactor only touched the `if volume is not None:` branch (volume-iteration), not `play_uri`. The failure path is the same as before Leg 04. Leg 04's smoke test ran `say("Kitchen")` AND `say("all")` cleanly — strong evidence the bug is intermittent or state-dependent in a non-topology way. Re-reproduction during this debrief with `list_groups` evidence proves the topology hypothesis wrong.

**Recommended next step**: a one-leg maintenance spike before Flight 02 (or as Flight 2's first leg). Log `coord.uid` and `coord.group.coordinator.uid` immediately before the failing `play_uri` at `controller.py:328`, run smoke, see what diverges. Don't bundle into Flight 02's documentation-cleanup scope — keep that flight pure text.

## Test Metrics

This is the **first** flight debrief in `mcp-sonos`. No priors to compare against. Seeding the baseline:

| Metric | Flight 01 |
|--------|-----------|
| Prior flight debriefs | 0 |
| Unit test count | 0 (no framework — `pytest` returns `No module named pytest`) |
| Smoke scripts | 2 (`smoke_test.py`, `playlist_smoke.py`) |
| `smoke_test.py` wall-clock | 10.17s (FAIL — `say()` coordinator anomaly above) |
| `playlist_smoke.py` wall-clock | 28.96s (pass — natural-end, skip, stop mid-track all green) |
| Live hardware required | yes (both scripts) |
| Coverage measurement | n/a |

Future debriefs should compare against these numbers. Flight 4 (test scaffolding) will substantially change this picture by adding pytest scaffolding and a hardware-free regression net.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| Leg 04 used `_group_members_of(coord)` instead of `self._group_members_of(coord)` per the leg snippet | Helper is module-level, not a method; Developer caught the slip on reading the actual code | yes — recon should verify call shape, not just symbol existence |
| Leg 05 deferred end-to-end space-in-filename verification to Post-Flight | No staged space-containing file available; URL-correctness verified at unit level instead | partial — pre-mark hardware-dependent ACs as deferable in leg specs |
| Single Reviewer pass at flight end instead of per-leg Reviewer (per `/agentic-workflow` defaults) | Skill default | keep — the Reviewer caught what mattered without per-leg overhead |
| Per-leg commits (6) instead of single-flight commit | Architect's design-review recommendation; honored despite shared-file complexity | yes — per-leg commits preserved bisect value |

## Key Learnings

1. **Recon is the highest-leverage planning phase.** Two of Flight 01's three biggest design decisions (F2 controller-side filter, F5 helper option A) were driven by recon evidence the original maintenance report didn't surface. Future maintenance flights should always do Phase 1b recon against current code before designing legs.
2. **Defence-in-depth via shared validator module is the right pattern for input policy that spans the tool/controller/data-model layering.** `_urls.py` is the reference implementation. Speaker-name validation, AUDIO_PORT range, and playlist-name normalization are all candidates for the same pattern.
3. **Hardware-dependent verification is the dominant cost in this project.** Smoke tests are slow (29s for playlist_smoke), require hardware, and don't cover most of what Flight 01 changed. Flight 4 (test scaffolding) is the highest-leverage future investment.
4. **The `_group_members_of` design choice (return names, not objects)** is intentional and good — `say()` is the only caller that needs objects. Don't reverse the decision under refactor pressure.
5. **Anomaly hypotheses should be tested before they're documented as "likely transient."** The Leg 05 hypothesis cost time during this debrief — re-running smoke once mid-flight would have either confirmed or refuted the topology theory in 30 seconds.

## Recommendations

1. **Investigate the `say()` coordinator bug before Flight 02 lands.** One-leg maintenance spike. Add to mission-level Known Issues now (this debrief does that). Candidate first unit test for Flight 4 if `_resolve_coordinator` proves to be the root cause.
2. **Update CLAUDE.md** with the `_urls.py` defence-in-depth pattern and the `AUDIO_MEDIA_ROOT` lazy-validation pattern. Bundle this into Flight 02 (documentation-cleanup) since it's already touching docs.
3. **Half-adopted `HttpUrl` alias in `server.py`**: either remove or fully adopt. Trivial — bundle into Flight 02 if natural.
4. **Pre-mark hardware-dependent ACs as deferable** in leg specs (a one-line convention in ARTIFACTS.md or a leg-template note).
5. **For Flight 4 (test scaffolding)**: F1 takeover path and the `say()` coordinator bug are the two highest-value first unit-test targets — both reproduce hardware-free against a SoCo fake.

## Action Items

- [ ] Add `say()` coordinator bug to mission Known Issues (this debrief does it on commit).
- [ ] Future maintenance spike: instrument `controller.py:328` `coord.play_uri` to log `coord.uid` vs `coord.group.coordinator.uid` and find the divergence.
- [ ] Codify the `_urls.py` defence-in-depth pattern in CLAUDE.md (Flight 02 candidate).
- [ ] Codify "eager parse, lazy validate" for env vars in CLAUDE.md (Flight 02 candidate).
- [ ] Resolve the `HttpUrl` alias half-adoption in `server.py` (Flight 02 candidate).
- [ ] Decide on a leg-template convention for hardware-dependent ACs.
