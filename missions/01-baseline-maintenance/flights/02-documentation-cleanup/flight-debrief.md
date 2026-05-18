# Flight Debrief: Documentation Cleanup

**Date**: 2026-05-18
**Flight**: [Documentation Cleanup](flight.md)
**Status**: landed
**Duration**: 2026-05-18 (planning + execution same day, ~1 hour wall-clock)
**Legs Completed**: 6 of 6

## Outcome Assessment

### Objectives Achieved
All four maintenance findings (F4, F6, F10, F11) and all three Flight 01 debrief carry-forwards landed cleanly. Six legs across 8 commits (1 flight-start + 6 per-leg + 1 landing artifacts). The doc-traps are gone, the dead code is gone, LAN IPs are anonymized, README's tool count is correct, and two patterns that emerged in Flight 01 are now codified in CLAUDE.md as project convention.

### Mission Criteria Advanced
4 of 14 mission success criteria ticked (F4, F6, F10, F11). Flight 2 of 4 checked off in the mission's flight list. Mission now at 10/14 complete. Remaining: F7 (Flight 4 — test scaffolding), F8/F13/F17 (Flight 3 — supply-chain hardening).

## What Went Well

- **Bundling decision validated.** Six legs across shared documentation surface (CLAUDE.md touched by Legs 03 + 05; server.py by Legs 01 + 06; playlists.py/controller.py inherited from F4/F6 scope) was the right call. Spawning a separate flight for the three debrief follow-ups would have created artificial scaffolding cost for ~5 lines of CLAUDE.md edits plus one deletion. The bundling held because none of the follow-ups required new recon — Flight 01's debrief had already done it.
- **Snippet-vs-call-site verification lesson from Flight 01 was honored.** No `self.X` vs `X` slips this flight. Leg 06's `grep -n "HttpUrl"` baseline at `legs/06-resolve-httpurl-alias.md:41` deliberately validates uniqueness before mutation. Leg 05's snippets are markdown prose with no call-shape exposure.
- **CLAUDE.md codifications are accurate to live code.** Leg 05's two new bullets describe what `_urls.py` and `AUDIO_MEDIA_ROOT` actually do — verified by independent grep at three import sites (`server.py:17,78,238`, `controller.py:18,160`, `playlists.py:27,142,160`) and two `controller.py` codepaths (init parse at `:94-95`; lazy validate at `:173-179`). No aspirational documentation.
- **Consolidated review-then-implement was effective** for text-dominant legs. Five of six legs used a single Developer agent for both phases without quality loss. The pattern saved ~5 agent spawns vs Flight 01's per-leg-review approach.
- **Leg 06 AC #4 ("happy-path `play_url(\"Kitchen\", \"http://...\")` still works") was correctly marked unchecked** with structural reasoning rather than forced-tick. The leg captured WHY the AC was unverifiable from this environment (no live hardware reachable for that exact path at that exact time) and why it was structurally safe regardless (consumer sites still bind the same validator). Worth keeping as a convention for hardware-dependent ACs across the project.

## What Could Be Improved

### Process

- **Consolidated review+implement has two visible failure modes** that didn't bite hard here but should be tracked:
  1. Leg 05's AC grep wording (`"eager parse | lazy validate"`) didn't match the actual prose (`"parse eagerly" / "validate lazily"`). Cosmetic mismatch — a separate phrase-level Reviewer would have caught it.
  2. Leg 06 picked up the orphaned scheme-allow-list comment block that sat above the deleted alias. Strictly outside the leg's stated scope; the Developer's justification (comment with no code → drift) is sound and was explicitly captured in the flight log, but a separate Reviewer might have flagged the scope expansion.
- **Rule of thumb that emerged**: split review and implementation when a leg can fail in non-obvious ways at runtime; consolidate when legs are textually independent and runtime-inert. Flight 02 was the latter category; Flight 01 was the former.
- **Action Item #4 from Flight 01 debrief (pre-mark hardware-dependent ACs as deferable in leg specs)** was not addressed in Flight 02 and isn't a fit for it — Flight 02 was doc-only. Carry forward to Flight 04 (test scaffolding) where it has the strongest motivation. The convention itself belongs in the `/leg` skill template or `.flightops/ARTIFACTS.md`, not in any single flight.

### Technical

- **`controller.py` class docstring at line 86 still reads "speakers cache + audio host + lock"** despite Leg 02 removing the lock. Reviewer flagged as non-blocking. Carry-forward candidate for whichever flight next touches `controller.py` — Flight 4 (test scaffolding) will, naturally.
- **A fourth `validate_http_url` call site at `server.py:269`** (inside `playlist_add_many` body, post-`raw["url"]`-stringify) wasn't enumerated in Leg 05's CLAUDE.md codification. The bullet says "three import sites" but a future contributor grepping will see four. Cosmetic — accuracy fix in a future doc pass.

### Documentation

- **The directory-listing-disabled guard from Flight 01's `audio_host.py:Handler` is still not codified** in CLAUDE.md. Flight 01's debrief flagged this as a missed documentation candidate; Flight 02 didn't bundle it (out of scope for the original F4/F6/F10/F11 frame). Worth a future `## When extending` addition: "Future contributors adding new file-serving paths shouldn't accidentally re-enable enumeration via `list_directory`."

## Anomaly: smoke_test.py Failed Differently This Run

**Status**: not a regression introduced by Flight 02. NEW failure mode distinct from the mission's existing `say()` coordinator Known Issue.

`smoke_test.py` failed at `2026-05-18` with: `No speaker named 'Kitchen'. Available: 'Dining Room', 'Fireplace Room', 'Lounge', 'Patio'` — the target speaker was missing from the SSDP discovery window. 30 seconds later, `playlist_smoke.py` ran successfully against Kitchen. SSDP discovery race, not topology change.

**Implication**: Flight 02 introduced no new failure modes (the divert criterion was not tripped). But the project now has at least two distinct smoke-test failure modes:
1. The known `say()` coordinator bug (mission Known Issue) — fires when discovery succeeds and the target IS a coordinator, but `play_uri` rejects on the resolved SoCo
2. SSDP-discovery flakiness — fires when 4 of 5 speakers are in the discovery window and the script picks a name that's missing

Neither is a Flight 02 issue. Both compound the cost of running smoke as a regression net.

**Recommended action before Flight 04 (test scaffolding)**: smoke scripts should honor `SONOS_IPS=` deterministic startup (`CLAUDE.md:101-102` already documents this as the preferred path, but `smoke_test.py` doesn't set it). Either set it inside the script as a default, or document the env-var requirement at the top of the script. This isn't a Flight 03 concern but is a Flight 04 prerequisite.

## Test Metrics

Second flight in this project; comparison against Flight 01 baseline:

| Metric | Flight 01 | Flight 02 | Delta |
|--------|-----------|-----------|-------|
| Prior flight debriefs | 0 | 1 | +1 |
| Unit test count | 0 | 0 | — |
| `pytest` available | no | no | — (Flight 04 will change this) |
| `smoke_test.py` wall-clock | 10.17s | 10.53s | +0.4s |
| `smoke_test.py` result | FAIL (`say()` coord bug) | FAIL (SSDP discovery race — different mode) | qualitative change |
| `playlist_smoke.py` wall-clock | 28.96s | 27.19s | -1.8s |
| `playlist_smoke.py` result | PASS | PASS | — |
| Live hardware required | yes | yes | — |
| Coverage measurement | n/a | n/a | — |

Playlist smoke is slightly faster (probably noise — ±2s on a 28s run). The `smoke_test.py` failure-mode shift is the meaningful change — the project now has two distinct hardware-dependent failure surfaces that need to be addressed before smoke tests can act as a real regression net.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| Leg 06 expanded scope to delete orphan comment block above the alias | Developer judgment — comment with no code is doc drift; reasoning captured in flight log | partial — the judgment is right, but consolidated review+implement made it possible without a Reviewer challenge. For runtime-inert legs, this is fine. |
| Consolidated review+implement agent for Legs 02-06 | Doc-only flight; per-leg review would have been overhead-heavy | yes for doc-only / runtime-inert flights; no for cross-cutting refactors |
| Per-leg commits (7 total: 1 flight-start + 6 legs) | Flight 01 convention preserved | yes — git-bisect value continues to justify the cost |
| smoke_test.py failure not investigated mid-flight | Different failure mode (SSDP race), not the known `say()` bug; divert criterion specifically allowed continuing if the failure mode matches the Known Issue | partial — the divert criterion needs sharper wording: "new failure mode" is fuzzy. Future flight specs should pre-enumerate the known failure modes and define "new" against them. |

## Key Learnings

1. **Doc-only flights have a different review economics than code flights.** Consolidating design-review and implementation for text-dominant legs saved agent overhead without quality loss. The split-then-bundle decision should be made per-flight, not as a universal pattern.
2. **Codifying patterns in CLAUDE.md is reversible cheap.** Leg 05's two new bullets describe-not-prescribe ("pick accordingly per new env var"). If a better pattern emerges, the bullets get rewritten — no code-level lock-in. Architectural elevation is appropriate at this stage of project maturity.
3. **Hardware-dependent ACs need a project-wide convention.** Flight 01's Action Item #4 is still open; this flight didn't need it (doc-only) but Flight 04 will live or die on it. The convention belongs in `/leg` skill template or `.flightops/ARTIFACTS.md`.
4. **Smoke-test reliability is a Flight 04 prerequisite.** Two distinct failure modes (the `say()` coordinator bug + SSDP-discovery flakiness) plus no unit tests means there's no real regression net today. Flight 04 must replace this, not just supplement it.
5. **Stacked PR pattern works.** Flight 02's PR targets Flight 01's branch as base; this preserves review independence (each flight stands on its own diff) while letting future flights build on landed work without waiting for upstream merge.

## Recommendations

1. **Before Flight 04, address SSDP-discovery flakiness in smoke scripts** by setting `SONOS_IPS=` as a sensible default. Small change (maybe 5 lines); removes one of two hardware-dependent failure modes.
2. **Carry the `controller.py:86` class docstring fix into Flight 04** when test scaffolding touches `controller.py` for DI refactoring. Trivial to bundle.
3. **Codify the directory-listing-disabled guard** in CLAUDE.md `## When extending`. Trivial; could be a Flight 03 bundle or stand-alone.
4. **For Flight 04's test scaffolding**: first unit tests should target `_urls.validate_http_url` directly (trivial, hardware-free, covers all consumer sites by contract). The eager/lazy env-var pattern needs a test convention (fakes that exercise the lazy path without setting `AUDIO_MEDIA_ROOT` in process env).
5. **Update the `/leg` skill template** to suggest AC verification strings be drawn from the leg's suggested prose, not paraphrased — closes the Leg 05 grep-phrase-mismatch class of near-miss.

## Action Items

- [ ] Pre-Flight-4: smoke scripts set `SONOS_IPS=` as deterministic-startup default (5-min change; removes one of two hardware-dependent failure surfaces).
- [ ] In Flight 4 (or earlier if natural): fix `controller.py:86` class docstring drift.
- [ ] In Flight 4: `_urls.validate_http_url` is the canonical first unit test target.
- [ ] In Flight 4: formalize hardware-AC pre-marking convention (carries over from Flight 01 debrief Action Item #4).
- [ ] Future doc-cleanup or Flight 3 bundle: codify the `audio_host.py:Handler` directory-listing-disabled guard in CLAUDE.md.
- [ ] Mission-control / methodology: update the `/leg` skill template so AC grep strings are drawn from the suggested prose (closes Leg 05 grep-phrase mismatch class).
