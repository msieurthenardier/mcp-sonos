# Leg: smoke-fallback-url

**Status**: completed
**Flight**: [Consolidation & Hygiene](../flight.md)

## Objective
Give `queue_smoke.py` and `reap_smoke.py` a fallback external MP3 URL so a single external-host outage no longer darkens both acceptance paths (finding T-7).

## Context
- Maintenance report 2026-06-02, finding **T-7** (Action Required, Test Systems / smoke resilience). Explicitly deferred to this cycle by the Mission-02 debriefs.
- Refined premise: the SoundHelix dependency affects **2 of 4** scripts, not 4 — only `queue_smoke.py:55-64` and `reap_smoke.py:64-73` hardcode SoundHelix URLs. `smoke_test.py` uses TTS only; `playlist_smoke.py` uses MCP-hosted/worker-path URLs. So a SoundHelix outage darkens the native-queue + reap-survival acceptance paths together — both with no SLA and no fallback.
- **Maintainer decision: do NOT commit a test MP3 into the repo.** Public MP3s are abundant — use a fallback external URL with try-next-on-failure instead.

## Inputs
- `queue_smoke.py` and `reap_smoke.py` with hardcoded SoundHelix `EXTERNAL_TRACKS`
- (Optional) live Sonos hardware to dry-run the smokes

## Outputs
- Both scripts define at least one fallback external MP3 host alongside SoundHelix, and select a reachable one (try primary, fall back on failure) before enqueuing.
- A single host outage degrades neither acceptance path.

## Acceptance Criteria
- [x] `queue_smoke.py` and `reap_smoke.py` reference at least two distinct external MP3 sources (primary + fallback), not SoundHelix alone
- [x] The scripts probe/select a reachable source at runtime (e.g. a HEAD/GET reachability check, or try-next on enqueue failure) rather than hardcoding one host
- [x] With the primary URL made deliberately unreachable, the scripts proceed using the fallback (dry-run or code-path inspection confirms)
- [x] No MP3 file is committed to the repo (`git status` shows no new binary); the `.gitignore` audio-blob exclusions are unaffected
- [x] The unit suite is unaffected (these scripts are not collected by `testpaths=["tests"]`)

## Verification Steps
- Read both scripts: confirm primary + fallback sources and the selection logic
- `git status --short` → no committed MP3
- If hardware available: run `queue_smoke.py` with the primary URL pointed at a dead host → confirm it falls back and still enqueues; otherwise trace the fallback code path by inspection
- `pytest` → unchanged (sanity)

## Implementation Guidance

1. **Add a fallback source** — pick a second well-known public MP3 host (or a
   second SoundHelix path is NOT sufficient — it must be a different host to
   actually de-risk). Define `EXTERNAL_TRACKS_PRIMARY` and `EXTERNAL_TRACKS_FALLBACK`
   (or a list of source pools).

2. **Select at runtime** — add a small reachability probe (`urllib`/`requests`
   HEAD or a short GET) that picks the first reachable pool; or attempt enqueue
   with the primary and retry with the fallback on failure. Keep it simple — these
   are operator-run scripts, not the unit net.

3. **Consider the shared scaffold** — finding I-6 (smoke-script copy-paste) is
   out of scope, but if a tiny `_smoke_common.py` is the natural home for the
   shared track pools + selection helper, creating it here is acceptable (and
   pre-empts I-6 for these two scripts). Do not over-engineer.

## Edge Cases
- **Fallback must be a different host** — two SoundHelix paths share the same SPOF.
- **No network at smoke time** — the scripts already require hardware + network;
  the fallback only addresses single-host outage, not total offline. Document
  that limitation in the script docstring if not already clear.
- **Honor the no-committed-MP3 constraint** — even a "tiny" file is out per the
  maintainer's decision.

## Files Affected
- `queue_smoke.py` - primary + fallback sources, selection logic
- `reap_smoke.py` - primary + fallback sources, selection logic
- (optional) `_smoke_common.py` - shared track pools + selection helper

---

## Post-Completion
Completion steps — status transitions, flight-log update, checking off in the parent flight, and commit — are Flight Control protocol, driven by the execution workflow (flight-end review + single commit). Do not commit; mark the leg `landed` and signal `[LAND:leg]`.

## Citation Audit (Flight Director, 2026-09-26 resume)
- `queue_smoke.py:EXTERNAL_TRACKS` (lines ~51-66) and `reap_smoke.py:EXTERNAL_TRACKS` (lines ~59-74): SoundHelix-only, all `https://www.soundhelix.com/examples/mp3/SoundHelix-Song-{1,2,3}.mp3`. Confirmed 2026-09-26.
- **FD design note:** CLAUDE.md "Stream format reality" — plain HTTP MP3 is the safe Sonos path; HTTPS is fragile. Prefer a fallback host that serves plain-HTTP MP3 (verify it actually responds with an `audio/mpeg` body before choosing it). The reachability probe must use a short timeout (≤5 s) so a dead primary doesn't stall the smoke. Probe from the MCP host is a proxy for speaker reachability — acceptable for an operator-run smoke; say so in the docstring.
