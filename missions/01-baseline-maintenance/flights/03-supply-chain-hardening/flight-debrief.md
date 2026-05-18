# Flight Debrief: Supply-Chain Hardening

**Date**: 2026-05-18
**Flight**: [Supply-Chain Hardening](flight.md)
**Status**: landed
**Duration**: 2026-05-18 (planning + execution same day, ~1.5 hour wall-clock)
**Legs Completed**: 3 of 3

## Outcome Assessment

### Objectives Achieved
All three maintenance findings (F8, F13, F17) landed cleanly. Default Piper voice has a pinned SHA-256 cross-verified against HuggingFace's LFS pointer; FastMCP is capped at `<4`; `pip-audit` is in dev extras with a clean **0/0/0/0 baseline across 104 packages**. The pre-pin tampered-cache attack vector is closed via the verify-existing path.

### Mission Criteria Advanced
3 of 14 mission success criteria ticked (F8, F13, F17). Flight 3 of 4 checked off. **Mission now at 13/14 complete** — only F7 (Flight 4 test scaffolding) remains.

## What Went Well

- **Layered design review paid off cleanly.** F8 went through both `/flight` review (caught the TOFU-from-local-cache risk + pre-pin verify-existing gap) and `/leg` review (caught the signature-shape regression + quarantine message granularity + thread-safety invariant). All 4 leg-review decisions and 3 flight-review decisions made it through to the final code without slippage. Each layer caught issues the other didn't.
- **Hardware-independent verification across ALL 3 legs.** First flight to achieve this. F8 used direct function calls + `dd` tamper test; F13 used `pip show` + `py_compile`; F17 used `pip-audit` itself. The persistent `say()` coordinator bug + SSDP-discovery race didn't block any leg's confidence. Worth promoting to a `/flight` skill design heuristic: prefer scope orderings that admit hardware-free verification.
- **Split-vs-consolidate rule from Flight 02 held on first cross-flight application.** F8 split caught 4 substantive issues during design review (runtime-semantics class); F13 + F17 consolidation produced zero-rework commits (textually independent + runtime-inert). The rule's prediction matched outcomes precisely. Two flights isn't yet a pattern — Flight 04 will be the real test.
- **F8 correctly DID NOT follow the `_urls.py` pattern.** The codified defense-in-depth pattern (Flight 02's CLAUDE.md addition) explicitly applies to **cross-cutting** input validation enforced at **multiple call sites**. F8's hash policy has one enforcement surface (`tts.py`); extracting to `_voice_hashes.py` would have been pattern-cargo-culting. The implementation honored the spirit (single-source-of-truth dict, shared helper used by both download + verify-existing paths) without misapplying the form. This is exactly the calibration the codified pattern's "describe-not-prescribe" wording was designed to enable.
- **Auditable supply-chain pins.** The HuggingFace LFS pointer cross-reference (full hash + URL + byte-size second-factor) is recorded in flight log Decisions. A future maintainer can re-verify the chain end-to-end from the artifact alone.
- **Flight-start commit (`275e787`)** gives `git bisect` a clean "before Flight 03 changes" anchor. Continued from Flight 02; preserve.

## What Could Be Improved

### Process

- **`_verified_voices` thread-safety invariant is documented in a code comment but not enforced.** If a future caller invokes `_ensure_voice` outside `_VoiceCache.get` (which holds `_VoiceCache._lock`), the set mutation races. Low actual risk today (single caller); worth promoting the set into `_VoiceCache` itself (co-locate lock + verified set) when Flight 04's test scaffolding gives us a way to exercise the contract.
- **F8 AC #7** ("Hash-only verify path is cached in-process") was an implementation-detail AC, not behavioral. The leg's snippets already prescribed `_verified_voices`. AC was load-bearing as documentation but redundant as a verification gate. Pattern: when leg snippets are prescriptive enough to fix the implementation shape, the AC should test the OBSERVABLE behavior (second call faster than first), not the implementation detail.

### Technical

- **`_download` has a polymorphic `voice_name: str | None` parameter** where `None` is the "skip verification" sentinel (used for the config-file download). Mildly smelly. Could split into `_download_voice(...)` + `_download_config(...)`. Not worth doing pre-Flight-4; revisit when test scaffolding shapes the call surface.
- **F8 introduced 3 new code paths** (`_verify_or_log`, `_hash_voice_file`, verify-existing branch) but no unit test. These are **ideal hardware-free unit-test targets** — pure functions over bytes-on-disk, no SoCo dependency. The ad-hoc tamper-test that verified them is thorough but unrepeatable. Flight 04 must convert these into permanent regression net.

### Documentation

- **CLAUDE.md doesn't yet codify the supply-chain hardening idioms** (pinned-hash dict, trust-on-first-use logging, `.suspect` quarantine convention). Worth a `## Supply-chain hardening` bullet in `## When extending` if Flight 04 or a future micro-flight touches CLAUDE.md.
- **`KNOWN_VOICE_HASHES` audit-trail comment** in `tts.py` is good but doesn't reference the flight log Decisions entry. A `# Audit trail: missions/01-baseline-maintenance/flights/03-supply-chain-hardening/flight-log.md#decisions` pointer would make the audit chain traversable from code alone.
- **`.suspect` quarantine convention** isn't surfaced anywhere user-facing. README mentions hash-pinning but not what happens on mismatch. Low priority.

## Test Metrics

Third flight in this project. Three-way comparison:

| Metric | Flight 01 | Flight 02 | Flight 03 |
|--------|-----------|-----------|-----------|
| Prior debriefs | 0 | 1 | 2 |
| Unit tests | 0 | 0 | 0 |
| `pytest` available | no | no | no |
| `pip-audit` available | no | no | **yes (NEW)** |
| `pip-audit` wall-clock | n/a | n/a | **0.83s** |
| `pip-audit` results | n/a | n/a | **0/0/0/0** across 104 packages |
| `smoke_test.py` wall-clock | 10.17s | 10.53s | 10.45s |
| `smoke_test.py` result | FAIL (`say()` coord) | FAIL (SSDP race) | FAIL (`say()` coord — back to mode 1) |
| `playlist_smoke.py` wall-clock | 28.96s | 27.19s | 29.20s |
| `playlist_smoke.py` result | PASS | PASS | PASS |

**Observations**:
- `smoke_test.py` failure mode flipped back to the `say()` coordinator bug. Confirms it's the **dominant** failure mode; SSDP race is intermittent. Two distinct failure surfaces; the dominant one stays open for Flight 04 / maintenance spike.
- `pip-audit` at 0.83s on cached OSV makes per-cycle re-scans nearly free — cheap to bake into routine-maintenance going forward.
- The 0/0/0/0 baseline is the seed for future delta comparisons. Any change at the next maintenance cycle is signal.

## Deviations and Lessons Learned

| Deviation | Reason | Standardize? |
|-----------|--------|--------------|
| `_verified_voices.add(voice)` added on fresh-download branch (`tts.py:163`) | Not in leg snippet; correct behavior (prevents redundant re-hash within same process after a download); Developer judgment | yes — captures the "verified during this process" semantic correctly |
| F8 implementation did NOT extract `KNOWN_VOICE_HASHES` to `_voice_hashes.py` despite the `_urls.py` pattern being codified | Single enforcement surface; cross-cutting pattern doesn't apply. Pattern's wording deliberately invites this divergence | yes — codified-pattern divergence is permitted when the structural context differs |
| Layered review (flight + leg + cumulative reviewer) for F8 vs consolidated for F13 + F17 | First cross-flight application of Flight 02's rule of thumb | yes — rule held; promote from emerging-rule to project convention |

## Key Learnings

1. **Layered design review compounds.** Flight + leg + cumulative-reviewer caught issues each individually would have missed. For runtime-semantics-class legs (TLS, file I/O, threading), the extra review layer is well worth its cost. For text/config-class legs, single-pass remains appropriate.
2. **Hardware-independent verification is a design choice, not an accident.** Flight 03's scope happened to be hardware-free for verification, but that property was visible at design time. Promote to `/flight` skill: ask "can this flight be verified without live hardware?" during planning.
3. **Codified patterns must accept divergence in their wording.** Flight 02's CLAUDE.md `_urls.py` pattern was written as "describe-not-prescribe" with explicit invite to pick differently per env var. F8 took that invite and shipped a one-enforcement-surface design without violating the pattern. This is the right calibration — patterns that lock-in future flights are worse than patterns that document successful patterns.
4. **Test-metrics baselines accumulate value across debriefs.** Three flights in, the metrics table tells a story: `pip-audit` came online, `smoke_test.py` failure modes are tracked, `playlist_smoke.py` is stable. Flight 04 will substantially change this picture by adding the unit-test column.
5. **The `say()` coordinator bug is the dominant smoke-test failure mode.** Three observations now: failed at Flight 02's `smoke_test.py` (different mode — SSDP race); failed at Flight 03's `smoke_test.py` (back to `say()`). The bug is reproducible — Flight 04 should target it with the first SoCoFake-driven test.

## Recommendations

1. **Flight 04 (test scaffolding) gets three canonical first unit-test targets** in priority order:
   - **F1 takeover path** (`session.coordinator_name`) — Flight 01 debrief's identified first target
   - **`_urls.validate_http_url`** — Flight 02 debrief's identified first target (multi-site coverage by contract)
   - **`_verify_or_log` + tamper path** — Flight 03's pattern; covers F8 regression net
2. **Flight 04 prerequisite work** (carry-forward consolidation):
   - SSDP-deterministic startup in smoke scripts (set `SONOS_IPS=` default) — Flight 02 debrief AI
   - `controller.py:86` class docstring drift fix — Flight 02 debrief AI
   - Hardware-AC pre-marking convention — Flight 01 debrief AI #4 (still open across 3 debriefs now)
3. **Investigate the `say()` coordinator bug as Flight 04's first SoCoFake-driven test.** It's reproducible; once `_resolve_coordinator` is exercised against a fake, the divergence between SoCo's view and Sonos firmware reality becomes observable. Closes the mission's only remaining real bug.
4. **Add pytest to the SAME `[dev]` optional-dependencies extra** in pyproject.toml — don't split into a separate `[test]` extra. pip-audit and pytest are both maintainer-only; one extra preserves the simple `pip install -e ".[dev]"` flow.
5. **Promote two emerging patterns to `/flight` skill design heuristics**:
   - "Hardware-free verifiability" as a flight scope criterion
   - "Split vs consolidate" rule (already informally applied; codify in the skill docs)

## Action Items

- [ ] Flight 04: first unit tests target `validate_http_url`, `_verify_or_log`, F1 takeover path, `say()` coordinator bug (in priority order).
- [ ] Flight 04 prereq: smoke scripts use `SONOS_IPS=` deterministic startup.
- [ ] Flight 04: fix `controller.py:86` class docstring drift while DI refactor is touching the file.
- [ ] Flight 04: formalize hardware-AC pre-marking convention (still open across 3 debriefs).
- [ ] Flight 04 or future flight: codify supply-chain hardening idioms in CLAUDE.md `## When extending`.
- [ ] Mission-control / methodology: promote "hardware-free verifiability" and "split vs consolidate" as `/flight` skill design heuristics.
- [ ] Future micro-cleanup: promote `_verified_voices` into `_VoiceCache` to enforce the thread-safety invariant rather than just documenting it.
- [ ] Future micro-cleanup: split `_download` into `_download_voice` and `_download_config` to remove the `voice_name: str | None` sentinel.
