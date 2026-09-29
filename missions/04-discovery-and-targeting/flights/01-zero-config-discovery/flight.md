# Flight: Zero-Config Discovery

**Status**: landed
**Mission**: [Zero-Config Discovery & Deterministic Speaker Targeting](../../mission.md)

## Contributing to Criteria
- [ ] With no speaker IPs configured, discovery finds every visible speaker in the household on the operator's LAN (all five, including Patio), across repeated runs *(behavior test `zero-config-discovery`)*
- [ ] When IPs are configured, they still work as a way in on networks where automatic discovery fails, and no longer hide household members that weren't listed *(behavior test `zero-config-discovery`)*
- [ ] When discovery finds no speakers, the tool error explains why and what the operator can set, rather than failing with an empty or generic result
- [ ] Tool schemas, README, and CLAUDE.md describe the new discovery behavior accurately *(discovery half of the mission docs criterion; targeting half is Flight 2)*
- [ ] The unit suite covers discovery selection without hardware, and passes *(discovery half; target-set grouping is Flight 2)*

---

## Pre-Flight

### Objective
Replace today's "exhaustive `SONOS_IPS` list, else SSDP-then-scan" discovery
with a pipeline that works with zero configuration on the operator's LAN.
The pipeline has three stages:
1. Configured IPs become optional **seeds**. The first live seed is expanded
   to the full visible household.
2. Otherwise, a **bounded subnet scan** derived from the advertised host IP
   runs, with an explicit `SONOS_SCAN_NETWORKS` override.
3. **SSDP** runs only as a last resort.

When every stage comes up empty, the server raises one diagnostic error that
names what was tried and what the operator can set. The error never comes back
as an empty list or a bare "No speaker named X". Docs, tool descriptions, and
smoke scripts are brought in line, and the version goes to 0.4.0.

### Open Questions
- [x] Subnet-scan scope on multi-NIC / VPN / large subnets → DD "Scan bound"
- [x] Discovery cost vs. cache TTL → DD "Cache freshness"
- [x] Seed expansion incl. invisible devices (Boost, bonded satellites) → DD "Seed handling"
- [x] Configured-IP fallback (try each until one answers) → DD "Seed handling"
- [x] Keep SSDP at all? → DD "Pipeline order" (maintainer: keep as last resort)
- [x] Override env-var name → DD "Scan bound" (maintainer: `SONOS_SCAN_NETWORKS`)
- [x] Version bump → DD "Version" (maintainer: 0.4.0 in this flight)
- [x] HAT leg? → maintainer: no. The behavior test covers it; save the HAT for Flight 2, where playback can be heard.

### Design Decisions

**Pipeline order: seeds → bounded scan → SSDP (last resort)**
- Each stage runs only if the previous one produced no visible speakers.
- Rationale: seeds are the cheapest and most deterministic when configured.
  The bounded scan is fast and reliable on this LAN (5/5 runs found all five
  speakers at 0.51–0.59 s, probed 2026-09-28). SSDP failed 3/3 here, but it
  stays because it covers hosts whose speakers sit outside the host's /24.
  It costs about 5 s, and only on the failure path.
- Trade-off: on a network where both seeds and scan fail but SSDP works,
  discovery takes about 5.5 s or more per refresh. That is acceptable
  because it is not a regression from today's default path.

**Seed handling: `SONOS_IPS` = ordered seeds, first live seed wins, expand via `visible_zones`**
- `SONOS_IPS` keeps its name, so the existing env contract keeps working.
  Its meaning changes from "exhaustive list" to "ways in".
- Seeds are tried in order. Each one is gated by a quick TCP reachability
  probe on port 1400 (sub-second timeout) before any UPnP call, because a dead
  IP costs about 4.1 s via SoCo on this host (probed 2026-09-28).
- The first seed that answers is expanded with its `visible_zones`. This
  returns the full visible household and excludes invisible devices such as
  the Boost and bonded satellites. Probe on 2026-09-28: `SoCo(".53").visible_zones`
  returned the 5 speakers, and `all_zones` added the Boost at `.48`.
- Speakers are still filtered by `_safe_is_visible` so a zone that went offline
  mid-discovery is dropped.
- If no seed answers, fall through to the scan. The per-seed outcomes are
  recorded for diagnostics.
- Rationale: this satisfies both "configured IPs still work as a way in" and
  "don't hide unlisted members". It also tolerates a rebooting seed.
- Trade-off: an operator who used `SONOS_IPS` to *restrict* the visible set
  loses that ability. The mission accepted this, and the README will call it
  out.

**Scan bound: derive from the advertised host IP, clamp to ≥ /24; `SONOS_SCAN_NETWORKS` overrides**
- Default: take `lan_host_ip()` (which already honors `HOST_IP`) and find the
  adapter that carries that IP (`ifaddr`, a SoCo dependency). Use its network
  prefix, clamped to at least /24 (at most 254 hosts). If no adapter carries
  the IP, use the IP's /24.
- Scan via `soco.discovery.scan_network(networks_to_scan=[...],
  multi_household=False, include_invisible=False)`.
- Override: `SONOS_SCAN_NETWORKS=cidr[,cidr...]` replaces the derived network
  entirely. Explicit entries are not clamped. Entries broader than /16 are
  rejected. Malformed or rejected entries are skipped and recorded in the
  diagnostics trace. If no valid entries remain, the scan stage is skipped
  and recorded.
- Rationale: SoCo's default merges every private network on every adapter
  (the mission flagged this). The host IP is the network the speakers must be
  able to reach anyway, because the audio host is advertised on it. This host
  is a single real LAN adapter (`eth1 192.168.86.173/24`) plus a harmless
  `10.255.255.254/32`.
- Trade-off: `multi_household=False` stops at the first household found. With
  two households on one subnet, which one wins is unspecified. To pin one,
  set `SONOS_IPS`, since seeds run first. This limitation is documented.

**Diagnostics: one `NoSpeakersFound` error carrying the stage trace**
- Raised by the discovery function when every stage yields zero visible
  speakers. The message names:
  - each seed and its outcome (unreachable, not Sonos, etc.)
  - the networks scanned, plus any rejected `SONOS_SCAN_NETWORKS` entries
  - the SSDP result
  - actionable hints: `SONOS_IPS`, `SONOS_SCAN_NETWORKS`, `HOST_IP`, same
    LAN/VLAN, and the Sonos firmware ≥ 85 UPnP toggle
- The controller propagates it from `_speakers_fresh`, so `list_speakers`,
  `refresh_speakers`, and every name-resolving tool surface it. An empty list
  is never cached. Today an empty result causes re-discovery on every call;
  that continues, but now each call reports why.
- Observability (verified 2026-09-28): FastMCP forwards the exception text
  word for word as `ToolError: Error calling tool '<name>': <message>`.
- Trade-off: `list_speakers` changes from "may return `[]`" to "raises when
  nothing is found". The mission criterion requires this.

**Amendment (in-flight, 2026-09-28): learned seeds + rate-limited scan**
- The original "Pipeline order" decision above stands as written. Hardware
  probing after leg 01 showed that the full-speed scan (SoCo's default of 256
  threads) makes connections to real speakers fail for 1–3 s afterwards,
  with `ENETUNREACH`, `EHOSTUNREACH` and timeouts. A cold `list_speakers`
  failed once with `Errno 101`.
- Change: the IPs from the last successful discovery become in-process
  **learned seeds**, tried after configured seeds and before the scan. The
  scan uses `max_threads=32`: about 2.5 s, with no disruption in the trials.
- Cache contract for learned seeds:
  - Source of truth: the last successful discovery.
  - Rebuild trigger: every successful discovery replaces them.
  - Staleness: harmless. A stale IP fails the TCP gate and the pipeline
    falls through to the scan.
  - No invalidation is needed on forced refresh, because any live member
    reports the current household topology.
- Trade-off: a cold start takes about 2.5 s instead of 0.5 s, once per
  process. Steady-state refreshes take about 0.05–0.8 s and never scan.

**Cache freshness: 30 s TTL kept, plus one forced re-discovery on a name miss**
- Source of truth: the household topology on the LAN. Maximum acceptable
  staleness is 30 s, which is unchanged.
- Existing rebuild triggers stay: TTL expiry, `refresh_speakers`, the reboot
  invalidation, and the stale-coordinator retry invalidation.
- New trigger: when name resolution misses on a cached list, re-discover once
  and retry before raising `SpeakerNotFound`. This covers a speaker that was
  just added, renamed, or rebooted without making the agent call
  `refresh_speakers`.
- Rationale: steady-state cost is a ~0.5 s scan at most every 30 s, and zero
  when seeds answer. There is no need for background refresh or a longer TTL.
  A miss-triggered refresh fixes the one case where staleness is visible to
  the agent.
- Trade-off: a genuinely misspelled name now costs one extra discovery pass
  before the error.

**Forced refreshes bypass SoCo's own topology cache (from Architect review)**
- SoCo has a second cache layer beneath ours.
  - `SoCo` objects are per-IP singletons.
  - `player_name`, `is_visible`, `group`, `visible_zones`, and `all_zones` all
    go through `zone_group_state.poll()`.
  - `ZoneGroupState` is cached per household, process-wide, for
    `POLLING_CACHE_TIMEOUT = 5` s (`soco/zonegroupstate.py:ZoneGroupState.poll`
    and `soco/core.py:SoCo.zone_group_states`).
  - Re-running discovery within 5 s of the last poll therefore returns the same
    topology, even though the app-level cache was reset.
- Decision: add one controller method, `_invalidate_speakers()`. It zeroes
  `_speakers_ts` and calls `zone_group_state.clear_cache()` on one cached
  speaker per household. That is enough, because the state object is shared
  per household.
- Every *forced* refresh routes through it:
  - `refresh()` (the `refresh_speakers` tool)
  - the new name-miss retry
  - the `reboot()` invalidation
  - both stale-coordinator retry call sites, which are separate:
    - the `invalidate_speakers_cache` callback passed to `PlaylistManager` and
      used by `_play_via_queue`
    - the inline `invalidate=lambda: setattr(self, "_speakers_ts", 0.0)` in
      `SonosController.say`'s `_play_clip` closure
- Verified non-issues (Architect cycle 2):
  - An empty app cache, on first call or after a failed discovery, leaves
    nothing to clear. That is benign, because a new household's
    `ZoneGroupState` starts already expired.
  - `clear_cache()` never touches the network. It is a pure attribute write,
    and every cached speaker already has `household_id` resolved from its
    `is_visible` check. The chosen speaker can therefore be unreachable.
- Plain TTL expiry does not clear SoCo's cache. At a 30 s TTL it is already
  past the 5 s window.
- Rationale: without this, the miss retry and `refresh_speakers` would
  frequently see stale data, which defeats the exact behavior they exist for.
- Test: a unit test with a fake whose topology cache records `clear_cache()`
  proves that each forced path clears it and re-polls.

**Error taxonomy and newly-raising callers**
- `NoSpeakersFound` subclasses `RuntimeError`, the same as `lan_host_ip()`'s
  environment failure. It signals an environment or network failure, not bad
  input. `SpeakerNotFound(ValueError)` stays the bad-name error.
- Accepted, named behavior changes caused by `_speakers_fresh` raising instead
  of returning `[]`. Every tool that resolves a speaker name now raises
  `NoSpeakersFound` with diagnostics on total failure, instead of
  `SpeakerNotFound(name, [])`. In addition:
  - `dissolve_all_groups` and `partymode` raise instead of silently doing
    nothing (`count: 0`).
  - `say("all")` raises `NoSpeakersFound` instead of `RuntimeError("No speakers
    available")`. Its now-unreachable empty guard in `_say_all` is removed.
- Stale-coordinator retry into a total discovery failure: `resolve()` in
  `with_stale_coord_retry` is unguarded, so `NoSpeakersFound` propagates. In
  `_play_via_queue` this can leave the hardware queue loaded but unplayed.
  That matches today's outcome when the retry itself fails, and it is
  accepted. A unit test pins that the error surfaces as `NoSpeakersFound` from
  both `say` and `_play_via_queue`.
- The worker-engine loop already treats any resolve failure as "stop session"
  (a broad `except` in its track loop), so no change is needed there.

**Interface preservation: `discover_speakers()` stays zero-arg-callable and returns `list[SoCo]`**
- Existing tests replace `sp.discover_speakers` with zero-arg lambdas (see
  `tests/test_queue_resume.py`, `tests/test_reboot.py`, and
  `tests/test_say_coordinator.py`). New parameters are keyword-only with
  defaults, and the controller keeps calling it with no arguments.
- Stage functions are injectable seams so the pipeline is unit-testable
  without hardware: the seed probe, seed expansion, scan, SSDP, and adapter
  lookup. Tests must not depend on the conftest-pinned `HOST_IP=127.0.0.1`
  producing a real scan.
- Every other consumer of `speakers.py` is checked (`resolve_name`,
  `lan_host_ip`, `SpeakerNotFound`). Their signatures stay unchanged.

**Smoke scripts go zero-config**
- `smoke_test.py`, `playlist_smoke.py`, `queue_smoke.py`, and `reap_smoke.py`
  each call `os.environ.setdefault("SONOS_IPS", "192.168.1.51,...")` with
  placeholder IPs. Under seed semantics those would become dead seeds, so the
  defaults are removed.
- The CLAUDE.md Commands section drops the `SONOS_IPS=...` prefixes (keeping
  a note that it can still be set).

**Behavior-test apparatus: new `discovery_smoke.py`, driven from the shell**
- *Act*:
  - A root-level script in the style of the existing smoke scripts. It drives
    an in-process FastMCP `Client`, the same code path the agent uses.
  - It calls `list_speakers` N times (default 3) and then `refresh_speakers`,
    under whatever `SONOS_IPS` / `SONOS_SCAN_NETWORKS` the shell sets.
  - Each scenario runs as a fresh process, so env reads and the cache start
    clean.
- *Observe*:
  - The script prints one JSON line per call:
    `{call, elapsed_s, speakers: [{name, ip}]}`.
  - It exits non-zero, printing the `ToolError` text, on failure.
  - Read path: `_speaker_dict` already returns `name` and `ip`, and the
    `ToolError` text passes through word for word (both verified 2026-09-28).
    No test-only seam is needed.
- Rationale: stdout from a shell command is directly observable, stays within
  the shell frame, and needs no MCP restart of the operator's live server.

**Version: 0.3.0 → 0.4.0 in this flight**
- Meaningful behavior change: the `SONOS_IPS` semantics and discovery order
  both change. Each merge to `main` carries its own version, and Flight 2's
  breaking schema change will take 0.5.0.

### Prerequisites
- [x] venv at `<repo-root>/.venv`; suite green on `main` at `573d6f2`: **78 passed** (1.60 s)
- [x] Live household reachable from this host: 5 visible speakers at `.49–.53`, Boost at `.48` (probed 2026-09-28)
- [x] Bounded scan of `192.168.86.0/24` finds all 5 speakers reliably (5/5 runs, 0.51–0.59 s)
- [x] SSDP is non-functional on this host (3/3 empty on 2026-09-27), which makes the forced-failure step of the behavior test reachable
- [x] Tool error text reaches the MCP client word for word (FastMCP `ToolError` probe, 2026-09-28)
- [x] No new network services. The audio port range 8000–8999 is untouched, so there are no environment conflicts.

### Pre-Flight Checklist
- [x] All open questions resolved
- [x] Design decisions documented
- [x] Prerequisites verified
- [x] Validation approach defined (unit suite + behavior test `zero-config-discovery`)
- [x] Legs defined

---

## In-Flight

### Technical Approach
1. **`mcp_sonos/speakers.py`**: rebuild `discover_speakers` as the three-stage
   pipeline described above.
   - Add the seed probe (TCP 1400), seed expansion via `visible_zones`, the
     derivation of scan networks (host-IP adapter lookup, /24 clamp, and
     `SONOS_SCAN_NETWORKS` parse/validate), the bounded scan, and the SSDP
     last resort.
   - Record a per-stage trace, and add `NoSpeakersFound` built from that trace.
   - Update the module docstring.
2. **`mcp_sonos/controller.py`**:
   - `_speakers_fresh` propagates `NoSpeakersFound`.
   - Add `_invalidate_speakers()`, which zeroes the TTL and clears SoCo's
     topology cache. `refresh()`, the name-miss retry, `reboot()`, and the
     `PlaylistManager` invalidate callback all use it.
   - `_resolve` does one forced re-discovery on a miss before raising
     `SpeakerNotFound`.
   - Remove the dead empty guard in `_say_all`.
   - The docstring of `refresh()` says what it actually does.
3. **`mcp_sonos/server.py`**: fix the `refresh_speakers` description
   ("SSDP" → the real pipeline). The `list_speakers` description notes that
   it raises with diagnostics when nothing is found.
4. **Tests**:
   - First, extend the shared `tests/_fakes.py::SoCoFake`. Do not create a
     one-off fake. It needs:
     - a `household_id` field
     - a `zone_group_state` stub whose `.clear_cache()` records its calls
   - Without this, `tests/test_reboot.py` and `tests/test_say_coordinator.py`
     fail with `AttributeError` once their invalidation paths go through
     `_invalidate_speakers()`.
   - Then add a new `tests/test_discovery.py` covering:
   - stage order and short-circuiting
   - seed fallback past dead seeds
   - seed expansion that excludes invisible devices
   - scan-network derivation (adapter prefix, /24 clamp, IP not on any
     adapter, override replaces the derived network, malformed and too-broad
     overrides rejected)
   - SSDP only when the scan is empty
   - `NoSpeakersFound` message content and its `RuntimeError` base
   - controller miss-triggered re-discovery
   - every forced-refresh path clearing SoCo's topology cache
   - `NoSpeakersFound` propagating through the stale-coordinator retry
     (`say` and `_play_via_queue`)
   Existing zero-arg stubs keep passing.
5. **Docs**:
   - README: configuration table (`SONOS_IPS` as seeds, the new
     `SONOS_SCAN_NETWORKS`, `HOST_IP` also bounds the scan), MCP config
     example, troubleshooting, prerequisites, the "Discovery cache" caveat,
     the Portable-speakers note, and the file-tree comment.
   - `.env.example`
   - CLAUDE.md: Commands and Operating constraints. Replace "prefer
     `SONOS_IPS`" with the new contract.
   - README agent system prompt, if it mentions discovery.
6. **Smoke**: remove the placeholder `SONOS_IPS` defaults from the four
   scripts. Add `discovery_smoke.py` (the apparatus).
7. **Version**: set `mcp_sonos/__init__.py` `__version__` to `"0.4.0"`.
8. **Hardware verification**: run `/mission-control:behavior-test zero-config-discovery`.

### Checkpoints
- [x] Discovery pipeline + diagnostics + controller miss-refresh landed; unit suite green (78 + new = 112)
- [x] Forced refreshes (`refresh_speakers`, name-miss retry, reboot, stale-coordinator retry) proven to bypass SoCo's 5 s topology cache, with a unit test
- [x] Docs, tool descriptions, smoke scripts, version 0.4.0 aligned
- [x] Behavior test `zero-config-discovery` passes on the operator's LAN

### Adaptation Criteria

**Divert if**:
- The bounded scan proves unreliable across repeated runs on hardware (misses
  a speaker because of ARP timing). In that case, re-plan the scan timeout or
  retry strategy rather than widening the scope silently.
- The bounded scan's `multi_household=False` early exit (the first Sonos IP to
  answer wins) returns a partial household. That can happen if a speaker
  mid-reboot answers TCP but serves stale zones.
- Seed expansion via `visible_zones` returns stale or partial topology when
  the seed is mid-reboot. That calls into question the "first live seed wins"
  decision.
- Keeping `discover_speakers()` zero-arg forces contortions. In that case,
  stop and decide explicitly whether to update the test stubs.

**Acceptable variations**:
- Exact probe or scan timeouts, and the structure of the trace object.
- Splitting stage helpers across private functions within `speakers.py`.
- Wording of the diagnostic message, as long as it names every stage and
  the env-var hints.

### Legs

> **Note:** These are tentative suggestions, not commitments. Legs are planned and created one at a time as the flight progresses. This list will evolve based on discoveries during implementation.

- [x] `01-discovery-pipeline`: seeds → bounded scan → SSDP pipeline,
  `SONOS_SCAN_NETWORKS`, `NoSpeakersFound` diagnostics, controller
  miss-refresh, unit tests, docs/tool descriptions, zero-config smoke scripts
  + `discovery_smoke.py`, version 0.4.0. *High-risk tier (cache behavior +
  shared-module interface), so it gets a design review.* Landed 2026-09-28.
- [x] `02-learned-seeds-gentle-scan`: *(added in flight, 2026-09-28)* The
  full-speed subnet scan was found to disrupt follow-up LAN connections for
  1–3 s. This leg adds learned seeds, so the steady state never scans, and
  limits the scan to 32 threads. *High-risk tier (a new cache).* See the
  flight log.
- [x] `03-hardware-discovery-verification`: run behavior test
  `zero-config-discovery` on the operator's LAN. Fixes found here loop back
  as new commits before the flight lands.

---

## Post-Flight

### Completion Checklist
- [x] All legs completed
- [ ] Code merged
- [x] Tests passing
- [x] Documentation updated

### Verification
- `.venv/bin/python -m pytest -q` green, with discovery covered by `tests/test_discovery.py`
- `/mission-control:behavior-test zero-config-discovery` passes (run log under `tests/behavior/zero-config-discovery/runs/`)
- `grep -rn "SSDP discovery" mcp_sonos/server.py` finds no inaccurate description
- `grep -n 'setdefault("SONOS_IPS"' *.py` returns nothing
- `mcp_sonos/__init__.py` reads `0.4.0`, and `tests/test_version.py` passes
