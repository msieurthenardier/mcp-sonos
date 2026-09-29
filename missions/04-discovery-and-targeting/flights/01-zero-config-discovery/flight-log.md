# Flight Log: Zero-Config Discovery

**Flight**: [Zero-Config Discovery](flight.md)

## Summary
Flight planned 2026-09-28. Leg 01 (`discovery-pipeline`) landed 2026-09-28:
unit suite 78 -> 112 passing, docs/smoke/version aligned to 0.4.0, hardware
sanity check (`discovery_smoke.py --runs 1`) green against the live
household. Leg 02 (hardware behavior-test verification) not yet run.

Update 2026-09-28: a post-landing hardware check found the full-speed scan
briefly disrupting LAN connections; the flight adapted in place with a new
Leg 02 (`learned-seeds-gentle-scan`), and the hardware behavior-test
verification leg was renumbered to Leg 03 (see Flight Director Notes
below). Leg 02 landed 2026-09-28: unit suite 112 -> 118 passing, a
rate-limited scan (`max_threads=32`) plus in-process learned seeds so
steady-state discovery no longer scans, three repeat hardware checks
green with no anomalies. Leg 03 not yet run.

---

## Leg Progress

### discovery-pipeline (Leg 01)
**Status**: landed
**Started**: 2026-09-28
**Completed**: 2026-09-28

#### Changes Made
- `mcp_sonos/speakers.py`: rebuilt `discover_speakers()` as the three-stage
  pipeline (seeds -> bounded scan -> SSDP), each stage short-circuiting the
  next on success. Added the seams `_probe_port`, `_expand_seed`,
  `_seed_stage`, `_adapter_prefix_for`, `_default_scan_network`,
  `_scan_networks` (derivation + `SONOS_SCAN_NETWORKS` override/validation),
  `_scan`, `_ssdp`, and `NoSpeakersFound(RuntimeError)` with a
  `_diagnostic_message` builder that names every seed's outcome, the
  network(s) scanned plus rejected override entries, the SSDP result, and
  the `SONOS_IPS`/`SONOS_SCAN_NETWORKS`/`HOST_IP`/same-LAN/UPnP-toggle
  hints. `resolve_name`, `SpeakerNotFound`, `lan_host_ip`, `safe_filename`
  are unchanged; `discover_speakers(*, timeout=5)` is still zero-arg
  callable, `timeout` now keyword-only.
- `mcp_sonos/controller.py`: added `_invalidate_speakers()` (zeroes the TTL,
  clears SoCo's per-household `ZoneGroupState` cache once per distinct
  `household_id`, swallows per-speaker exceptions, no-op on an empty
  cache, never discovers). Routed all four forced paths through it:
  `refresh()`, the new `_resolve()` name-miss retry (exactly one extra
  discovery, `NoSpeakersFound` from the retry propagates unwrapped),
  `reboot()`, and the `PlaylistManager` `invalidate_speakers_cache`
  callback. Also fixed `say()`'s inline stale-coordinator retry lambda to
  use it (previously bypassed `_invalidate_speakers`, zeroing only the TTL).
  Removed the now-dead `if not speakers: raise RuntimeError("No speakers
  available")` guard in `_say_all` (`_speakers_fresh()` now raises
  `NoSpeakersFound` instead of ever returning `[]`) — this is also what
  makes `dissolve_all_groups`/`partymode`/`say("all")` raise instead of
  silently no-op'ing, with no code change needed at those call sites since
  they already route through `_speakers_fresh()`. Updated the `refresh()`
  docstring.
- `mcp_sonos/server.py`: `refresh_speakers` description no longer says
  "SSDP"; `list_speakers` description notes it raises diagnostics when
  nothing is found.
- `mcp_sonos/__init__.py`: `__version__ = "0.4.0"`.
- `tests/_fakes.py`: `SoCoFake` gained `household_id` (default
  `"Sonos_FAKE_HOUSEHOLD"`) and `zone_group_state` (new `FakeZoneGroupState`
  dataclass whose `clear_cache()` counts calls). All 78 pre-existing tests
  pass unmodified with these fields added.
- `tests/test_discovery.py` (new, 34 tests): stage order/short-circuiting,
  dead-seed fallback, seed-expansion visibility filtering (including a
  zone whose `is_visible` raises), a Boost-only seed counting as "no
  speakers", scan-network derivation (adapter `/24` and `/22->/24` clamp,
  no-adapter fallback, `SONOS_SCAN_NETWORKS` override replacing derivation
  entirely, malformed + `/8` rejection, all-invalid -> scan skipped),
  `NoSpeakersFound` `RuntimeError` base and full message-content coverage,
  the controller's name-miss retry (success, exhaustion, and
  `NoSpeakersFound` propagating through it unwrapped), every forced path
  clearing SoCo's cache (`refresh`, name-miss, `reboot`, the
  `PlaylistManager` callback, `say`'s inline retry) with plain TTL expiry
  proven NOT to clear it, and `NoSpeakersFound` propagating through the
  stale-coordinator retry from both `say()` and
  `PlaylistManager._play_via_queue`. All hardware-free: every stage
  function and the `ifaddr`/`sp.SoCo` seams are monkeypatched, no real
  sockets or scans.
- `tests/test_version.py`: now asserts `0.4.0`.
- `pyproject.toml`: added `ifaddr>=0.2` as an explicit direct dependency
  (previously only transitive via `soco`; `mcp_sonos.speakers` now imports
  it directly for the adapter-network lookup).
- `smoke_test.py`, `playlist_smoke.py`, `queue_smoke.py`, `reap_smoke.py`:
  removed the placeholder `os.environ.setdefault("SONOS_IPS", "192.168.1.5x
  ...")` lines (dead seeds under the new seed semantics). `reap_smoke.py`'s
  two `list_speakers` reachability checks (`phase_load`, `phase_control`)
  are now wrapped in `try/except Exception -> _fail(...)`, matching
  `queue_smoke.py`'s existing pattern, so a `ToolError` from an empty
  `NoSpeakersFound` result reaches `_fail` instead of crashing the script.
  Refreshed the stale "set SONOS_IPS to the correct IPs" text in both
  scripts to point at the new seeds/scan/SSDP diagnostic instead.
- `discovery_smoke.py` (new, repo root): `--runs N` (default 3) calls
  `list_speakers` N times then `refresh_speakers` once via an in-process
  FastMCP `Client`, printing one `{"call", "elapsed_s", "speakers":
  [{"name","ip"}]}` JSON line per call; prints the tool-error text to
  stderr and exits non-zero on failure. Sets no env defaults.
- `README.md`: Configuration table (`SONOS_IPS` reframed as seeds,
  `SONOS_SCAN_NETWORKS` added, `HOST_IP` noted as bounding the default
  scan), MCP config example (env block no longer implies `SONOS_IPS` is
  needed), "Picking values", Network requirements bullet 1, the
  Portable-speakers note, the "Discovery cache is 30s" caveat (now
  mentioning the name-miss refresh), and the `speakers.py` file-tree
  comment. Checked the agent system prompt — it doesn't mention discovery
  specifics, so left unchanged per the leg's guidance.
- `.env.example`: `SONOS_IPS` reframed as seeds; added
  `SONOS_SCAN_NETWORKS`; `HOST_IP` comment now notes it bounds the default
  scan derivation.
- `CLAUDE.md`: Commands section's five smoke-script lines drop the
  `SONOS_IPS=...` prefix (with a note it can still be set) and gained a
  `discovery_smoke.py --runs 1` line. The two "Operating constraints" SSDP
  bullets now describe the seeds -> scan -> SSDP contract and
  `NoSpeakersFound`. Added a "When extending" bullet naming
  `_invalidate_speakers()` + SoCo's 5s `ZoneGroupState` cache as an
  invariant for any new forced-refresh path.

#### Notes
- Test count: 78 -> 112 (34 new in `tests/test_discovery.py`), all green:
  `timeout 180 .venv/bin/python -m pytest -q` -> `112 passed in ~2s`.
  `pytest-timeout` is indeed not installed, so the `timeout 180` wrapper
  was used throughout, per the Developer design review's citation audit.
- Wheel build sanity check: `.venv/bin/python -m build --wheel` succeeded
  as `mcp_sonos-0.4.0-py3-none-any.whl` (hatchling dynamic version wired
  correctly).
- Hardware verification (the one permitted read-only check):
  `timeout 60 .venv/bin/python discovery_smoke.py --runs 1` against the
  live household — exit 0, two JSON lines, each listing all 5 speakers
  (Dining Room/Fireplace Room/Kitchen/Lounge/Patio at `.49`-`.53`). No
  `SONOS_IPS`/`SONOS_SCAN_NETWORKS` was set for this run, so it exercised
  the real bounded-scan path end-to-end: `list_speakers` (cold) took
  4.082s (includes `SonosController` init / audio-host bind), the
  immediately-following `refresh_speakers` (forced re-discovery, cache
  already warm) took 0.771s — consistent with the flight's probed
  ~0.5-0.6s scan cost plus per-speaker `GetHouseholdID` overhead the
  Developer design review flagged for Leg 02's timing budget.
- No existing test assertions were weakened or removed; all 78
  pre-existing tests pass with zero modifications beyond the additive
  `SoCoFake` fields required by the leg spec.
- No deviations from the leg spec's acceptance criteria. The only
  additions beyond the letter of the spec: a "no seeds configured" trace
  line (`SONOS_IPS` empty) for a clearer `NoSpeakersFound` message, and
  documenting `ifaddr` in `pyproject.toml` per the Implementation
  Guidance's "add it only if the project's style lists transitive
  dependencies it uses directly" (it now does, directly, for the adapter
  lookup).

### learned-seeds-gentle-scan (Leg 02)
**Status**: landed
**Started**: 2026-09-28
**Completed**: 2026-09-28

#### Changes Made
- `mcp_sonos/speakers.py`: added `SCAN_MAX_THREADS = 32` (module constant,
  not an env var, comment cites the 2026-09-28 measurement) and passed it
  to `soco.discovery.scan_network(..., max_threads=SCAN_MAX_THREADS)` in
  `_scan`. Factored the configured-seed stage's gate-then-expand loop out
  of `_seed_stage` into a shared `_gate_and_expand_stage(ips, label)`, used
  by both stages so trace lines read distinctly ("seed <ip>: ..." vs.
  "learned seed <ip>: ..."). Added module-level `_learned_seed_ips: list[str]`
  (process-wide, replaced wholesale via `_record_learned_seeds` on every
  successful `discover_speakers()`, left untouched on `NoSpeakersFound`),
  `_learned_seed_stage(configured_ips)` (skips any IP already tried as a
  configured seed this call, silent on a cold start, records a distinct
  trace line when every learned seed is filtered out by overlap), and the
  test-only `_reset_learned_seeds()`. Wired the new stage into
  `discover_speakers` between the configured-seed and scan stages, and the
  success path now sorts before recording so learned seeds are stored in
  name order. Updated the module docstring, `NoSpeakersFound`'s docstring,
  and `_diagnostic_message`'s header line for the new four-stage pipeline;
  renumbered the stage-comment banners (1-4).
- `tests/test_discovery.py`: gave the local `_FakeZone` test double an
  `ip_address` constructor parameter (default derived from the zone name's
  hash, so no existing call site needed to change) — required before any
  learned-seed code could run, since recording learned seeds reads
  `.ip_address` off every returned speaker and about 10 existing pipeline
  tests construct `_FakeZone` without one. Added an autouse
  `_reset_learned_seeds` fixture that resets `sp._learned_seed_ips` before
  and after every test. Added 6 new tests: a learned seed recorded after a
  successful scan is used by the next call with `_scan` never invoked;
  dead learned seeds fall through to the scan; a failed call (everything
  empty) leaves previously-recorded learned seeds untouched; a configured
  seed that already failed the gate is not re-probed as a learned seed
  (asserted via a probe-call-counting spy); `_scan` passes
  `max_threads=SCAN_MAX_THREADS` (== 32) to `soco.discovery.scan_network`;
  and the `NoSpeakersFound` message includes a tried-and-dead learned
  seed's outcome. No existing assertion was weakened.
- `README.md`: added a "Discovery cache" caveat bullet stating the scan
  only runs cold or when nothing already known answers (learned seeds are
  tried first, so a repeat call in-process normally never scans), and that
  the scan is deliberately rate-limited because a full-speed scan disrupts
  this host's LAN connections to the real speakers on some hosts (WSL2
  mirrored networking) — numbers omitted from the prose per the leg spec.
  Updated the "Picking values" zero-config bullet and the file-tree
  comment to name the learned-seed stage; updated the "No speakers found"
  troubleshooting bullet to say seed outcomes cover both configured and
  learned seeds.
- `CLAUDE.md`: expanded the "Discovery is zero-config" Operating
  constraints bullet to name the four-stage pipeline, learned seeds, and
  the rate-limited scan (naming `SCAN_MAX_THREADS` as a fixed constant,
  not an env var, without restating the raw numbers).
- `missions/.../flight.md`: checked off leg 02 in the Legs list.
- Leg status: `ready` -> `in-flight` -> `landed` (this file).

#### Notes
- Test count: 112 -> 118 (6 new), all green:
  `timeout 180 .venv/bin/python -m pytest -q` -> `118 passed in ~2s`.
  `grep -n "max_threads" mcp_sonos/speakers.py` confirms the one call site.
- Hardware verification — the leg's permitted read-only check,
  `env -u SONOS_IPS -u SONOS_SCAN_NETWORKS timeout 60
  .venv/bin/python discovery_smoke.py --runs 3`, run three times as three
  independent fresh processes (each one cold: no learned seeds carried
  between processes, only within a process's own three `list_speakers`
  calls + one `refresh_speakers`):
  - Run 1: exit 0. Cold first `list_speakers` 0.959s; subsequent calls
    0.237s, 0.243s; `refresh_speakers` 0.320s. 5/5 speakers on every call.
  - Run 2: exit 0. Cold first call 0.942s; subsequent 0.234s, 0.201s;
    `refresh_speakers` 0.235s. 5/5 speakers on every call.
  - Run 3: exit 0. Cold first call 0.928s; subsequent 0.202s, 0.219s;
    `refresh_speakers` 0.241s. 5/5 speakers on every call.
  - No anomalies (no `ENETUNREACH`/`EHOSTUNREACH`/timeouts) in any of the
    three runs — a contrast with the post-Leg-01 check, where 1 of 3 fresh
    processes hit `[Errno 101] Network is unreachable` right after the
    full-speed (256-thread) scan. Every `refresh_speakers` call (served by
    a learned seed, no scan) finished well under the leg's 1.5s bar, and
    even the cold first call — which does run the 32-thread scan in each
    fresh process, since learned seeds don't survive across processes —
    stayed under 1s in all three runs, faster than the ~2.5s scan-only
    figure probed earlier (that probe measured the scan in isolation;
    end-to-end here overlaps it with `SonosController` init).
- No deviations from the leg spec's acceptance criteria or Implementation
  Guidance. The only addition beyond the letter of the spec: the
  "learned seeds: all already tried as configured seeds" trace line for
  the edge case where every learned seed happens to overlap the configured
  set, so that case doesn't read as "stage never ran" in a
  `NoSpeakersFound` message.

---

## Flight Director Notes

### 2026-09-28: Planning probes (ground truth for the design decisions)
- `lan_host_ip()` returns `192.168.86.173` (`eth1 /24`). The other adapters
  are `lo` and `10.255.255.254/32`.
- Bounded `scan_network(networks_to_scan=["192.168.86.0/24"])` found all 5
  speakers in 5 of 5 runs, taking 0.51–0.59 s each.
- `SoCo("192.168.86.53").visible_zones` returns the 5 speakers. `all_zones`
  returns those plus the Boost at `.48`.
- A dead seed (`192.168.86.200`) takes about 4.1 s to fail with
  `ConnectionError`. That cost is why the flight adds a quick TCP 1400 gate.
- FastMCP passes the exception text word for word as `ToolError`.
- Four smoke scripts `setdefault` placeholder `SONOS_IPS` (`192.168.1.5x`).
  Under seed semantics those become dead seeds, so the flight removes them.
- Suite baseline: 78 passed, 1.60 s.

### 2026-09-28: Design review, cycle 1 (Architect)
- Verdict: approve with changes.
- **[high] Fixed.** SoCo's per-household `ZoneGroupState` 5 s cache
  (`POLLING_CACHE_TIMEOUT`) would make the name-miss retry and
  `refresh_speakers` return stale topology. I verified this in
  `soco/zonegroupstate.py` and `soco/core.py`. Added a design decision:
  `_invalidate_speakers()` clears SoCo's cache on every forced-refresh path.
  This also covers reboot and the stale-coordinator invalidate callback.
- **[medium] Accepted and tested.** `NoSpeakersFound` propagates through the
  unguarded `resolve()` in `with_stale_coord_retry`. It can leave the queue
  loaded but unplayed, which is the same outcome as a failed retry today.
- **[low] Fixed.**
  - Removed the dead empty guard in `_say_all`.
  - Named the changes for `dissolve_all_groups`, `partymode`, and `say("all")`,
    which now raise `NoSpeakersFound`.
  - `NoSpeakersFound` subclasses `RuntimeError`.
  - Added a scan-race divert trigger.
- Substantive change (the new cache design decision reaches the retry path),
  so I spawned a second review cycle.

### 2026-09-28: Design review, cycle 2 (Architect), final
- Verdict: approve with changes. Both cycle-1 fixes were verified against the
  SoCo source and the controller.
- **[high] Fixed.** The shared `SoCoFake` has no `household_id` or
  `zone_group_state`, so rerouting the reboot and `say` invalidation would
  break existing tests. Technical Approach step 4 now extends `SoCoFake` first.
- **[high] Fixed.** `say`'s inline retry lambda is a second stale-coordinator
  call site, separate from `PlaylistManager`'s callback. Both are now named
  in the design decision.
- Recorded non-issues: clearing with an empty cache is benign, and
  `clear_cache()` makes no network call.
- These were precision fixes to call sites and test scaffolding with no change
  in direction. This was the last of the maximum 2 cycles, so no further review
  was run.

### 2026-09-28: Execution start
- The operator approved the flight and authorized running the whole mission
  autonomously. The flight is `in-flight` on branch
  `flight/01-zero-config-discovery`, and the planning artifacts were committed
  as `80878fc`. The mission was set to `active`.
- The phase file `.flightops/agent-crews/leg-execution.md` loaded, and its
  structure is valid.
- **Leg 01 `discovery-pipeline`: tiered HIGH-RISK.** It changes cache and
  freshness behavior (the TTL, the name-miss refresh and SoCo cache
  invalidation). It also changes a shared-interface contract that existing
  consumers rely on: `_speakers_fresh` now raises, and `SoCoFake` is used
  across about 10 test files. A Developer design review follows.

### 2026-09-28: Leg 01 design review, cycle 1 (Developer)
- Verdict: approve with changes. The citation audit was accurate. `ifaddr` is
  a real dependency of SoCo. `pytest-timeout` isn't installed, so the leg's
  `timeout 180` fallback applies.
- **[medium] Fixed.** `reap_smoke.py` crashes on `ToolError` instead of
  reaching `_fail`. Added acceptance criteria to wrap its two checks and to
  refresh the stale "set SONOS_IPS" text.
- **[low] Addressed in guidance.**
  - `SoCoFake.is_visible` is always truthy.
  - `sp.SoCo` is the seam for faking seed expansion.
  - `_invalidate_speakers` must not discover, which keeps the
    `test_say_coordinator` count at 2.
  - The flight's error-taxonomy bullet now says every tool that resolves a
    name is affected.
- Timing caveat noted for leg 02: `_safe_is_visible` makes one
  `GetHouseholdID` round-trip per speaker. End-to-end `elapsed_s` is what the
  behavior test asserts, with a limit under 3 s, not the raw scan time.
- These were only additive precision changes, so no second cycle was run. The
  leg is marked `ready`. [HANDOFF:review-needed]

### 2026-09-28: Leg 01 [LAND:leg] received. Post-landing hardware check found scan disruption, so a new leg was added
- Developer reported 112 passed (78 → 112) and version 0.4.0. The permitted
  hardware check found 5/5 speakers.
- The Flight Director re-ran `discovery_smoke.py` three times as fresh
  processes:
  - Run 1 exited 1: `Error calling tool 'list_speakers': HTTPConnectionPool(host='192.168.86.51', port=1400) ... [Errno 101] Network is unreachable`.
  - The other two runs exited 0, with the first call taking 3.53 s and
    0.80 s.
- Root cause, isolated by probes:
  - Without a scan, 100/100 sequential TCP 1400 connects to the 5 speakers
    were clean (≤ 25 ms each).
  - Immediately after `scan_network` at the default 256 threads, a 5–6 s
    polling window showed `E101`/`E113` and 1 s timeouts in 2 of 3 trials.
  - At `max_threads=32` the scan took ~2.55 s with zero anomalies (2/2). At
    8 threads it took ~8.55 s, also with zero anomalies.
  - Learned-seed expansion (`SoCo(ip).visible_zones` after `clear_cache()`)
    took 0.05 s.
  - Neighbor-table settings: `gc_thresh3` is 1024 and `unres_qlen` is 101.
    The table is not overflowing, so this is burst behavior, most likely
    WSL2 mirrored-networking ARP handling.
- **Adaptation criterion triggered** ("bounded scan proves unreliable").
  Re-planned within the flight's scope, with no change to mission criteria:
  - Leg 01 stays as landed. It is not reopened, because landed legs are
    immutable.
  - **New leg 02 `learned-seeds-gentle-scan`**, tiered **HIGH-RISK** because
    it introduces a new in-process cache.
  - The hardware leg is renumbered to 03.
- A design-decision amendment was appended to the flight spec; the original
  text is preserved.
- Behavior-test step 2 timing was revised (cold first call under 5 s, later
  calls under 1.5 s), with a revision note in the spec.
- Pre-existing, noted for later: `_speaker_dict` makes a UPnP call per
  speaker, so one speaker's transient failure fails the whole
  `list_speakers`. This is outside this flight, and I'll consider a squawk at
  the debrief.

### 2026-09-28: Leg 02 design review, cycle 1 (Developer)
- Verdict: approve with changes. Citations were accurate. The learned-seed
  state cannot leak into other test files, because they all stub
  `discover_speakers`.
- **[high] Fixed.** The test double `_FakeZone` in `test_discovery.py` has no
  `ip_address`, so recording learned seeds would break about 10 existing
  tests. Guidance step 3 now adds the attribute to the fake first; no
  assertion changes.
- **[medium] Fixed.** Guidance step 4 now says how the learned stage receives
  the configured IPs to skip: they are passed in and matched by exact string.
- Also clarified in verification why the under-1.5 s limit holds in each
  fresh process.
- The changes were additive precision only, so there was no second cycle.
  The leg is marked `ready`. [HANDOFF:review-needed]

### 2026-09-28 — Flight review: Reviewer [HANDOFF:confirmed] for legs 01–02 (118 passed); one non-blocking doc nit (README stage count) fixed at commit; legs 01–02 → completed; leg 03 (hardware behavior test) pending.

### 2026-09-28: Flight commit, PR, and leg 03 designed
- Flight commit `b9dee81` was pushed, and draft PR #11 is open.
- **Leg 03 `hardware-discovery-verification`: tiered LOW-RISK.** It changes
  no code; it is acceptance verification only. No design review is needed.
  Running `/mission-control:behavior-test zero-config-discovery`.

### 2026-09-29: Leg 03 `hardware-discovery-verification` completed
- `/mission-control:behavior-test zero-config-discovery` **passed 8/8**. Run
  log: `tests/behavior/zero-config-discovery/runs/2026-09-29-02-27-28.md`.
- Execution: live mode, with Executor and Validator on Sonnet and cold cache.
  The system under test was `b9dee81`.
- Timings:

  | Scenario | Cold call | Later calls |
  |---|---|---|
  | No configuration | 0.84–1.45 s | 0.19–0.25 s |
  | Only Kitchen configured | 0.52 s | — |
  | Dead seed + Patio | 1.49 s | — |
  | All seeds dead | 3.90 s | refresh 2.24 s |

  The all-dead-seeds case: every call re-probes each dead configured seed,
  at about 1 s each.
- Step 7's diagnostic error named each stage and the three env hints.
- **Carried to the debrief**: configured seeds are re-probed ahead of learned
  seeds on every discovery, so a stale `SONOS_IPS` costs about 1 s per dead
  entry per refresh. A candidate follow-up is to try learned seeds before
  configured ones, or to demote configured seeds that fail. The spec now says
  step 6's missing timing bound is deliberate, following the Validator's
  readability note.
- The spec status was promoted from `draft` to `active`.
- The leg is marked `completed`. It is a verification-only leg, so it had no
  code and needed no review.

### 2026-09-29: Flight landed [COMPLETE:flight]
- All 3 legs are `completed`, and the flight log has an entry for each. Docs
  were verified by the flight review: README, `.env.example`, CLAUDE.md and
  the tool descriptions.
- Flight status is `landed`, and it is checked off in `mission.md`. PR #11
  was marked ready for review. "Code merged" remains open until the operator
  merges.
