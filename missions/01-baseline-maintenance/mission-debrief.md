# Mission Debrief: Baseline Maintenance

**Date**: 2026-05-18
**Mission**: [Baseline Maintenance](mission.md)
**Status**: completed
**Duration**: 2026-05-18 (single day — planning + 4 flights + 4 debriefs, ~7 hours wall-clock)
**Flights Completed**: 4 of 4

## Outcome Assessment

### Success Criteria Results

| Criterion | Status | Flight | Notes |
|-----------|--------|--------|-------|
| F1 — playlists.py takeover AttributeError fix | met | F01-L01 | One-line rename, regression-pinned in F04-L03 |
| F2 — play_file allow-list + dir-listing block | met | F01-L02 | Threat-model boundary tightened |
| F3 — AUDIO_PORT range validation | met | F01-L03 | Reuses existing `PORT_RANGE` constant |
| F4 — say docstring + playlists.py keying invariant | met | F02-L01 | Doc-as-traps eliminated |
| F5 — say() routes through `_group_members_of` | met | F01-L04 | CLAUDE.md invariant preserved |
| F6 — dead lock + unused imports removed | met | F02-L02 | Includes `import threading` cleanup |
| F7 — pytest scaffolding + SoCoFake + DI refactor | met | F04-L02+L03 | 10 tests pass in ~0.21s hardware-free |
| F8 — Piper voice hash pin + verify-existing | met | F03-L01 | Cross-verified against HuggingFace LFS pointer |
| F10 — LAN IP anonymization | met | F02-L03 | `192.168.1.x` placeholder family |
| F11 — README tool count (19→32) | met | F02-L04 | One-word fix |
| F12 — URL-encode audio host filenames | met | F01-L05 | `urllib.parse.quote` |
| F13 — fastmcp<4 dependency cap | met | F03-L02 | Resolver no-op (3.3.1 within cap) |
| F14 — URL scheme allow-list (http/https) | met | F01-L06 | Defense-in-depth at tool + controller + manager |
| F17 — pip-audit baseline | met | F03-L03 | 0/0/0/0 across 104 packages |

**14 of 14 success criteria met.** Plus 3 Flight 02 debrief carry-forwards (`_urls.py` codification, eager-parse/lazy-validate codification, HttpUrl alias removed) + 4 Flight 03 debrief carry-forwards (validate_http_url tests, _verify_or_log tests, F1 takeover regression test, `say()` coordinator bug investigation+fix) + 1 scope-expanded leg (smoke-script DI regression fix). **22 actual items resolved.**

### Overall Outcome

Yes — the mission achieved its stated outcome and then some. The bar set at planning ("free of the real correctness bug; properly scoped `play_file`; validated `AUDIO_PORT`; documentation aligned; supply-chain hashes; unit-test scaffolding") was met. The mission's only remaining real bug at flight start (the `say()` coordinator routing issue) was carried correctly across three debriefs and resolved in Flight 04 — not as scope creep but as the natural consequence of finally having a hardware-free regression net to reproduce it against.

**The qualitative shift is the durable outcome**: mcp-sonos transitioned from "well-maintained but hardware-dependent" to "well-maintained with a hardware-free regression net (10 pytest tests + pip-audit + Piper hash pin)." The 14 findings are the immediate scoreboard; the test scaffolding is the multiplier for every future mission.

## Flight Summary

| Flight | Status | Legs | Key outcome |
|--------|--------|------|-------------|
| 01 Correctness and Capability Hardening | completed | 6 | Real bug fixed (F1), threat-model boundary tightened (F2), input validation hardened (F3, F12, F14), helper invariant preserved (F5) |
| 02 Documentation Cleanup | completed | 6 | Doc-traps eliminated (F4, F11), dead code removed (F6), public-repo hygiene (F10), patterns codified in CLAUDE.md (3 debrief carry-forwards) |
| 03 Supply-Chain Hardening | completed | 3 | Piper voice pinned + verify-existing (F8), fastmcp<4 cap (F13), pip-audit baseline (F17). **First hardware-free flight.** |
| 04 Test Scaffolding | completed | 5 (4 planned + 1 scope expansion) | F7 satisfied; `say()` bug fixed; smoke-script DI regression caught and closed within-flight |

## What Went Well

### Process

- **The `routine-maintenance` → `mission` → `flight` cascade scoped correctly.** 14 findings + 3 + 4 carry-forwards + 1 scope expansion = ~22 items resolved in one mission, one day, one developer. Splitting into multiple missions would have lost the natural ordering (F7's DI refactor enables tests that retroactively pin F1's takeover fix).
- **Per-leg commits delivered the promised git-bisect value.** 32 commits across the mission, each compilable, each tagged to one finding or carry-forward. The cost was negligible (~5% overhead); the benefit was real (Leg 4-05 narrowed the smoke-script regression to "Leg 4-02 introduced; Leg 4-04 observed; Leg 4-05 fixed" via git history alone).
- **Cross-flight Known Issues lifecycle worked.** The `say()` coordinator bug surfaced in Flight 01 debrief, persisted through Flights 02 and 03 with sharpening hypotheses, was reproduced + fixed in Flight 04. The mission's Known Issues section is the right anchor; debriefs reliably referenced it; the methodology carried the issue cleanly across flights without losing context.
- **The "describe-not-prescribe" pattern codification wording (Flight 02 CLAUDE.md addition for `_urls.py`) demonstrated value.** Flight 03's F8 implementation correctly opted out of the pattern because the surface didn't fit — pattern's deliberate divergence-invitation wording prevented cargo-culting. This is the methodology win of the mission.

### Technical

- **Hardware-free verifiability evolved from accident → heuristic → criterion.** Flight 01 was hardware-dependent end-to-end and paid for it (the `say()` bug went unfixed for three flights because smoke is the only verification path). Flight 03 was the first flight to achieve full hardware-free verification across all legs. Flight 04 closed the loop by **building** the regression net (10 pytest tests in 0.21s).
- **The DI refactor (F7) was the multiplier.** Once `register_tools(mcp, controller)` existed, the pytest suite could exercise the controller hardware-free; the `say()` coordinator bug went from "intermittent and unverifiable" to "deterministic and pinned by 2 regression tests" in one leg.
- **Defense-in-depth at three surfaces (`_urls.validate_http_url`) is the reference architecture pattern.** One validator, three import sites (tool/controller/manager). Codified in CLAUDE.md. Future candidates named explicitly (speaker-name normalization, AUDIO_PORT range, playlist-name validation).

## What Could Be Improved

### Process

- **Cross-flight methodology debt has no escalation path.** Flight 01 debrief AI #4 ("pre-mark hardware-dependent ACs as deferable in leg specs") stayed open across all 4 debriefs and is **still open at mission close** — it's a `/leg` skill template change, not a project change, but no debrief had an escalation channel. **Recommendation**: flight debriefs should distinguish "project action items" from "methodology action items" and the latter should land in mission-control's backlog at debrief time, not at mission close.
- **Within-flight regression detection worked here because Flight 04 had an investigative leg.** Leg 4-02's DI refactor introduced the smoke-script regression; Leg 4-02's verification (`import mcp_sonos.server` clean, no port bind) was correct as far as it went, but didn't exercise `Client(mcp)`. Leg 4-04's investigative scope is what caught it. **Implication**: non-investigative flights have weaker within-flight regression detection. Worth considering whether every non-trivial flight should include at least one investigative or "exercise the full path" leg.
- **Live-hardware verification was elusive across the mission.** The maintainer's actual LAN doesn't match the project's `192.168.1.x` placeholders, so smoke tests didn't run from the orchestration environment after Flight 01's baseline. This is correct project hygiene (anonymization for public repo) but it means smoke tests became the maintainer's responsibility outside the orchestration loop. **Live-hardware smoke verification of the `say()` fix is still pending.**

### Technical

- **`_verified_voices` thread-safety invariant is documented in code comments but not enforced** (Flight 03 debrief). Carry-forward — promote into `_VoiceCache` (co-locate the lock with the verified set) in a future micro-flight.
- **`_download`'s `voice_name: str | None` parameter** is mildly polymorphic (`None` = "skip verification" sentinel for config files). Could split into `_download_voice` + `_download_config` for clarity. Not worth pre-test-scaffolding; revisit later.
- **`controller.py` class docstring drift** was caught and fixed in Flight 02, but it took two flights to surface. Worth a CLAUDE.md or pre-commit hook check that class docstrings are kept current relative to `__init__` state.

### Documentation

- **CLAUDE.md gained two codified patterns** (`_urls.py` defense-in-depth, AUDIO_MEDIA_ROOT eager-parse/lazy-validate) but the supply-chain hardening idioms (pinned-hash dict, trust-on-first-use logging, `.suspect` quarantine) from Flight 03 were not codified — Flight 03 debrief flagged this. **Recommendation**: post-mission micro-flight or fold into future maintenance to add a `## Supply-chain hardening` section to CLAUDE.md `## When extending`.
- **The `audio_host.py:Handler` directory-listing-disabled guard** from Flight 01 still isn't codified in CLAUDE.md. Flight 01 + Flight 02 debriefs both flagged this. Worth bundling with the supply-chain codification above.

## Lessons Learned

### Technical

1. **DI refactors are mission-multipliers.** F7 looked like one item among fourteen; it was actually the architectural pivot that enabled hardware-free regression net + reproducing the `say()` bug + pinning F1's takeover fix. Future missions should treat "make this testable" items with disproportionate priority because they unblock everything downstream.

2. **SoCo-vs-firmware divergence is real and invisible from the controller.** The `say()` coordinator bug fixed in F04-L04 wasn't a code logic error — `coord.uid == coord.group.coordinator.uid` agreed at the call site. The divergence lives between SoCo's in-process cache and Sonos firmware. The fix (`_play_uri_with_stale_coord_retry`: invalidate cache, retry once) is a pattern that should generalize to other SoCo transport calls if they exhibit similar symptoms (`play_url`, queue operations, etc.).

3. **Per-process caches need test-observability hooks.** `_iteration_event` on `PlaylistManager` is the reference example — production never reads it, tests use it to close polling races. Pattern likely applies to `_speakers_fresh`, `_verified_voices`, `_VoiceCache`, etc., when future test coverage extends.

### Process

4. **"Split vs consolidate" agent pattern held up across 4 flights with zero false predictions.** Codify in `/flight` skill: split design-review from implementation when leg failures manifest at runtime in non-obvious ways; consolidate when legs are textually independent and runtime-inert.

5. **"Hardware-free verifiability" is a flight scope criterion, not just a property.** Ask at planning time: "Can each leg be verified without production hardware/service? If not, why?" This surfaces dependencies on external state at the right phase (planning, not execution).

6. **Codified patterns must explicitly invite divergence.** Flight 02's `_urls.py` codification said "pick accordingly per new env var." Flight 03 took the invitation correctly (F8's `KNOWN_VOICE_HASHES` stayed in `tts.py` because the surface didn't justify the pattern). Patterns that lock in are worse than patterns that document successful instances with named applicability conditions.

7. **Mid-flight scope expansion is the right framing when the scope guard governs.** Leg 4-05 was a 5th leg added mid-flight because Leg 4-04 surfaced a regression Leg 4-02 introduced. Same flight closed it. A separate micro-flight would have lost coherence and required a new feature branch + stacked PR.

## Methodology Feedback (for Flight Control)

Four concrete improvements to mission-control:

1. **Promote "split vs consolidate" to `/flight` skill design heuristic.** Documented per-leg in this mission's flight debriefs; ready to codify in skill docs.

2. **Promote "hardware-free verifiability" to `/flight` skill scope criterion.** Explicitly observed in Flight 03 debrief; exemplified by Flight 04 design.

3. **Distinguish project AI vs methodology AI in flight debriefs.** Methodology AIs (like the still-open hardware-AC pre-marking convention) need an escalation path to mission-control's backlog, not just accumulation in project debriefs.

4. **Allow mid-flight scope expansion in `/agentic-workflow` when the surface guard governs.** Leg 4-05 worked cleanly; the methodology should make this an explicit, sanctioned pattern rather than an exception.

## Action Items

- [ ] Live-hardware smoke verification of the `say()` fix (maintainer-side; placeholder IPs don't match actual LAN)
- [ ] Promote `_verified_voices` into `_VoiceCache` to enforce thread-safety invariant rather than documenting it (Flight 03 carry-forward; future micro-flight)
- [ ] Codify supply-chain hardening idioms in CLAUDE.md `## When extending` (Flight 03 debrief carry-forward — pinned-hash dict, trust-on-first-use, `.suspect` quarantine)
- [ ] Codify `audio_host.py:Handler` directory-listing guard in CLAUDE.md `## When extending` (Flight 01 + Flight 02 debrief carry-forward)
- [ ] Split `_download` into `_download_voice` + `_download_config` (Flight 03 carry-forward; nice-to-have)
- [ ] **For mission-control**: codify "split vs consolidate" heuristic in `/flight` skill
- [ ] **For mission-control**: codify "hardware-free verifiability" criterion in `/flight` skill
- [ ] **For mission-control**: codify "describe-not-prescribe with named applicability" pattern-codification convention
- [ ] **For mission-control**: distinguish project vs methodology Action Items in flight-debrief crew prompt
- [ ] **For mission-control**: sanction mid-flight scope expansion in `/agentic-workflow` when surface guard governs
- [ ] **For `/leg` skill template**: pre-mark hardware-dependent ACs as deferable (carry-forward from Flight 01 debrief, open across all 4 debriefs)
- [ ] **For `/leg` skill template**: AC verification strings should be drawn from the leg's suggested prose, not paraphrased (Flight 02 carry-forward — Leg 05 grep-phrase mismatch)
